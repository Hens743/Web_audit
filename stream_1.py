import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urljoin, urlparse
import textstat
import base64
import io
import json
from concurrent.futures import ThreadPoolExecutor
import re

# --- Configuration ---
st.set_page_config(page_title="Website Auditor Pro", page_icon="🕵️‍♀️", layout="wide")

# --- Caching & Analysis Functions ---
@st.cache_data(ttl=1800)  # Cache for 30 minutes
def audit_page(url):
    """Performs a comprehensive audit on a single URL."""
    results = {'url': url, 'status_code': None, 'error': None}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        results['status_code'] = response.status_code
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results['soup'] = soup
        results['headers'] = response.headers
        
        # Basic SEO checks
        title = soup.find('title')
        results['title'] = title.text.strip() if title else ""
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        results['meta_description'] = meta_desc['content'].strip() if meta_desc else ""
        results['h1_tags'] = [h1.text.strip() for h1 in soup.find_all('h1')]
        
        return results
    except requests.exceptions.RequestException as e:
        results['error'] = str(e)
        return results

@st.cache_data(ttl=1800)
def run_pagespeed_insights(url):
    api_key = st.secrets.get("GOOGLE_PAGESPEED_API_KEY")
    if not api_key: return None, "Google PageSpeed API Key not found."
    api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy=mobile&category=performance&category=accessibility&category=seo&category=best-practices&key={api_key}"
    try:
        response = requests.get(api_url, timeout=90)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as e:
        return None, str(e)

def get_internal_links(base_url, soup):
    """Extracts unique internal links from a page."""
    links = {urljoin(base_url, a['href']) for a in soup.find_all('a', href=True)}
    return {link for link in links if urlparse(link).netloc == urlparse(base_url).netloc}

# --- UI Display Functions ---

def display_performance_audit(psi_report):
    st.header("Performance & Core Web Vitals ⚡", divider="rainbow")
    perf_category = psi_report.get('categories', {}).get('performance', {})
    if not perf_category: st.warning("Performance report not available."); return

    st.metric("Overall Performance Score", f"{perf_category.get('score', 0) * 100:.0f}/100")
    
    # Helper to display detailed tables from PSI data
    def display_audit_details(audit_id, columns):
        audit = psi_report.get('audits', {}).get(audit_id, {})
        if 'details' in audit and 'items' in audit['details']:
            items = audit['details']['items']
            if items:
                st.subheader(audit.get('title'))
                st.markdown(audit.get('description'))
                df = pd.DataFrame(items)
                st.dataframe(df[columns], width='stretch', hide_index=True)
    
    with st.expander("Key Opportunities for Improvement", expanded=True):
        display_audit_details('render-blocking-resources', ['url', 'totalBytes', 'wastedMs'])
        display_audit_details('uses-optimized-images', ['url', 'totalBytes', 'wastedBytes'])
        display_audit_details('uses-next-gen-images', ['url', 'totalBytes', 'wastedBytes'])
        display_audit_details('unused-javascript', ['url', 'totalBytes', 'wastedBytes'])
        display_audit_details('unused-css-rules', ['url', 'totalBytes', 'wastedBytes'])

def display_seo_audit(soup, psi_report, keyword):
    st.header("SEO Analysis 🔍", divider="rainbow")
    
    with st.expander("Keyword Analysis", expanded=True):
        if keyword:
            page_text = soup.get_text().lower()
            keyword_count = page_text.count(keyword.lower())
            word_count = len(page_text.split())
            density = (keyword_count / word_count * 100) if word_count > 0 else 0
            
            st.metric(f"Keyword Density for '{keyword}'", f"{density:.2f}% ({keyword_count} mentions)")
            
            title = soup.find('title').text if soup.find('title') else ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            h1s = [h1.text for h1 in soup.find_all('h1')]
            
            st.success(f"Keyword in Title: {'✅ Yes' if keyword.lower() in title.lower() else '❌ No'}")
            st.success(f"Keyword in Meta Description: {'✅ Yes' if meta_desc and keyword.lower() in meta_desc.get('content','').lower() else '❌ No'}")
            st.success(f"Keyword in H1 Tags: {'✅ Yes' if any(keyword.lower() in h1.lower() for h1 in h1s) else '❌ No'}")
        else:
            st.info("Enter a target keyword in the sidebar to run this analysis.")

    # ... (rest of the SEO display function)

def display_technical_audit(soup, url):
    st.header("Technical SEO Audit ⚙️", divider="rainbow")
    
    st.subheader("Crawling & Indexing")
    robots_url = urljoin(url, "/robots.txt")
    try:
        robots_res = requests.get(robots_url, timeout=5)
        if robots_res.status_code == 200:
            st.success(f"✅ Robots.txt found.")
            with st.expander("View robots.txt content"):
                st.code(robots_res.text)
        else:
            st.warning("⚠️ Robots.txt not found.")
    except requests.exceptions.RequestException:
        st.error("Could not check for robots.txt.")
        
    canonical_tag = soup.find('link', rel='canonical')
    st.success(f"**Canonical Tag:** {'✅ Present' if canonical_tag else '⚠️ Missing'}")
    if canonical_tag: st.info(f"Canonical URL: `{canonical_tag.get('href')}`")
    
    hreflang_tags = soup.find_all('link', rel='alternate', hreflang=True)
    st.success(f"**Hreflang Tags:** {'✅ Present' if hreflang_tags else 'ℹ️ Not found (only needed for multi-language sites)'}")


def display_crawl_results(crawl_data):
    st.header("Site Crawl Overview 🗺️", divider="rainbow")
    if not crawl_data: st.info("Crawl was not initiated or no links found."); return
    
    st.markdown(f"Analyzed **{len(crawl_data)}** pages linked from the homepage.")
    crawl_df = pd.DataFrame(crawl_data)
    crawl_df['H1 Count'] = crawl_df['h1_tags'].apply(len)
    st.dataframe(crawl_df[['url', 'status_code', 'title', 'H1 Count', 'error']], width='stretch', hide_index=True)

# --- Main App Logic ---
def main():
    st.sidebar.title("Configuration")
    url_input = st.sidebar.text_input("Enter Website URL", "https://www.streamlit.io")
    keyword_input = st.sidebar.text_input("Enter Target Keyword (Optional)")
    crawl_pages = st.sidebar.slider("Pages to Crawl (from homepage)", 1, 10, 3)

    st.title("🕵️‍♀️ Website Auditor Pro")
    st.markdown(f"### Comprehensive Audit for `{url_input}`")

    if st.sidebar.button("🚀 Audit Website", type="primary"):
        url = url_input if url_input.startswith(('http://', 'https://')) else 'https://' + url_input

        # --- Initial Page Audit ---
        with st.spinner(f"Auditing main page: {url}..."):
            main_page_data = audit_page(url)
            if main_page_data.get('error'):
                st.error(f"Failed to audit main page: {main_page_data['error']}"); return
            
            psi_results, psi_error = run_pagespeed_insights(url)
            if psi_error: st.warning(f"Could not get Google PageSpeed data: {psi_error}")

        # --- Site Crawl ---
        crawl_data = [main_page_data]
        if crawl_pages > 1:
            with st.spinner(f"Crawling up to {crawl_pages-1} additional pages..."):
                internal_links = get_internal_links(url, main_page_data['soup'])
                links_to_crawl = list(internal_links - {url})[:crawl_pages-1]
                
                with ThreadPoolExecutor(max_workers=5) as executor:
                    crawl_results = executor.map(audit_page, links_to_crawl)
                crawl_data.extend(list(crawl_results))
        
        # --- Display Results in Tabs ---
        psi_report = psi_results.get('lighthouseResult', {}) if psi_results else {}
        
        summary_tab, perf_tab, seo_tab, tech_tab, crawl_tab = st.tabs(
            ["Summary", "Performance", "SEO", "Technical", "Site Crawl"]
        )
        
        with summary_tab:
            # Code for summary tab - simplified for brevity
            st.metric("Overall Performance Score", f"{psi_report.get('categories', {}).get('performance', {}).get('score', 0) * 100:.0f}/100")
            st.metric("Overall SEO Score", f"{psi_report.get('categories', {}).get('seo', {}).get('score', 0) * 100:.0f}/100")
        with perf_tab:
            display_performance_audit(psi_report)
        with seo_tab:
            display_seo_audit(main_page_data['soup'], psi_report, keyword_input)
        with tech_tab:
            display_technical_audit(main_page_data['soup'], url)
        with crawl_tab:
            display_crawl_results(crawl_data)

if __name__ == "__main__":
    main()
