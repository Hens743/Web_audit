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
from collections import Counter

# --- Configuration ---
st.set_page_config(page_title="Website Auditor Pro", page_icon="🕵️‍♀️", layout="wide")

# A simple list of common English stop words for keyword analysis
STOP_WORDS = set([
    'a', 'about', 'above', 'after', 'again', 'against', 'all', 'am', 'an', 'and', 'any', 'are', "aren't", 'as', 'at',
    'be', 'because', 'been', 'before', 'being', 'below', 'between', 'both', 'but', 'by', 'can', "can't", 'cannot',
    'com', 'could', "couldn't", 'did', "didn't", 'do', 'does', "doesn't", 'doing', "don't", 'down', 'during',
    'each', 'few', 'for', 'from', 'further', 'had', "hadn't", 'has', "hasn't", 'have', "haven't", 'having', 'he',
    "he'd", "he'll", "he's", 'her', 'here', "here's", 'hers', 'herself', 'him', 'himself', 'his', 'how', "how's",
    'i', "i'd", "i'll", "i'm", "i've", 'if', 'in', 'into', 'is', "isn't", 'it', "it's", 'its', 'itself', "let's",
    'me', 'more', 'most', "mustn't", 'my', 'myself', 'no', 'nor', 'not', 'of', 'off', 'on', 'once', 'only', 'or',
    'other', 'ought', 'our', 'ours', 'ourselves', 'out', 'over', 'own', 'r', 'same', 'she', "she'd", "she'll",
    "she's", 'should', "shouldn't", 'so', 'some', 'such', 'than', 'that', "that's", 'the', 'their', 'theirs',
    'them', 'themselves', 'then', 'there', "there's", 'these', 'they', "they'd", "they'll", "they're", "they've",
    'this', 'those', 'through', 'to', 'too', 'under', 'until', 'up', 'very', 'was', "wasn't", 'we', "we'd",
    "we'll", "we're", "we've", 'were', "weren't", 'what', "what's", 'when', "when's", 'where', "where's",
    'which', 'while', 'who', "who's", 'whom', 'why', "why's", 'with', "won't", 'would', "wouldn't", 'you',
    "you'd", "you'll", "you're", "you've", 'your', 'yours', 'yourself', 'yourselves', 'www', 'https'
])

# --- Caching & Analysis Functions ---
@st.cache_data(ttl=1800)
def audit_page(url):
    """Performs a comprehensive audit on a single URL."""
    results = {'url': url, 'status_code': None, 'error': None, 'soup': None}
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        results['status_code'] = response.status_code
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        results['soup'] = soup
        results['headers'] = response.headers
        
        # Basic SEO checks for crawl summary
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

def suggest_keywords(soup):
    """Analyzes the text of a BeautifulSoup object to suggest keywords."""
    if not soup: return []
    for script_or_style in soup(["script", "style"]):
        script_or_style.decompose()
    text = soup.get_text()
    words = re.findall(r'\b\w{4,15}\b', text.lower())
    meaningful_words = [word for word in words if word not in STOP_WORDS and not word.isdigit()]
    return [word for word, _ in Counter(meaningful_words).most_common(10)]

def get_internal_links(base_url, soup):
    links = {urljoin(base_url, a['href']) for a in soup.find_all('a', href=True)}
    return {link for link in links if urlparse(link).netloc == urlparse(base_url).netloc}

# --- UI Display Functions ---

def display_summary(psi_results, soup):
    st.header("Audit Summary 📝", divider="rainbow")
    if not psi_results:
        st.error("Could not retrieve PageSpeed Insights data to generate a summary.")
        return

    report = psi_results.get('lighthouseResult', {})
    scores = {
        'Performance': report.get('categories', {}).get('performance', {}).get('score', 0) * 100,
        'Accessibility': report.get('categories', {}).get('accessibility', {}).get('score', 0) * 100,
        'SEO': report.get('categories', {}).get('seo', {}).get('score', 0) * 100,
        'Best Practices': report.get('categories', {}).get('best-practices', {}).get('score', 0) * 100,
    }

    cols = st.columns(4)
    cols[0].metric("Performance", f"{scores['Performance']:.0f}/100")
    cols[1].metric("Accessibility", f"{scores['Accessibility']:.0f}/100")
    cols[2].metric("SEO", f"{scores['SEO']:.0f}/100")
    cols[3].metric("Best Practices", f"{scores['Best Practices']:.0f}/100")
    
    st.divider()
    left_col, right_col = st.columns(2)
    with left_col:
        st.subheader("Mobile Viewport")
        screenshot_data = report.get('audits', {}).get('final-screenshot', {}).get('details', {}).get('data')
        if screenshot_data:
            st.image(base64.b64decode(screenshot_data.split(',')[1]), caption="Mobile Screenshot")
    with right_col:
        st.subheader("Key Information")
        st.info(f"**Title:** {soup.find('title').text if soup and soup.find('title') else 'N/A'}")
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        st.info(f"**Meta Description:** {meta_desc['content'] if meta_desc else 'N/A'}")

def display_performance_audit(psi_report):
    st.header("Performance & Core Web Vitals ⚡", divider="rainbow")
    perf_category = psi_report.get('categories', {}).get('performance', {})
    if not perf_category: st.warning("Performance report not available."); return

    st.metric("Overall Performance Score", f"{perf_category.get('score', 0) * 100:.0f}/100")
    
    def display_audit_details(audit_id, columns, title):
        audit = psi_report.get('audits', {}).get(audit_id, {})
        if 'details' in audit and 'items' in audit['details'] and audit['details']['items']:
            with st.expander(f"{title} - ({audit.get('displayValue', '')})", expanded=False):
                st.markdown(audit.get('description'))
                df = pd.DataFrame(audit['details']['items'])
                display_cols = [col for col in columns if col in df.columns]
                st.dataframe(df[display_cols], width='stretch', hide_index=True)
    
    display_audit_details('render-blocking-resources', ['url', 'totalBytes', 'wastedMs'], "Eliminate Render-Blocking Resources")
    display_audit_details('uses-optimized-images', ['url', 'totalBytes', 'wastedBytes'], "Properly Size Images")
    display_audit_details('uses-next-gen-images', ['url', 'totalBytes', 'wastedBytes'], "Serve Images in Next-Gen Formats")
    display_audit_details('unused-javascript', ['url', 'totalBytes', 'wastedBytes'], "Reduce Unused JavaScript")
    display_audit_details('unused-css-rules', ['url', 'totalBytes', 'wastedBytes'], "Reduce Unused CSS")

def display_seo_audit(soup, keyword):
    st.header("SEO Analysis 🔍", divider="rainbow")
    
    if keyword:
        with st.expander("Keyword Analysis", expanded=True):
            page_text = soup.get_text().lower()
            keyword_count = page_text.count(keyword.lower())
            word_count = len(page_text.split())
            density = (keyword_count / word_count * 100) if word_count > 0 else 0
            
            st.metric(f"Keyword Density for '{keyword}'", f"{density:.2f}% ({keyword_count} mentions)")
            
            title = soup.find('title').text if soup.find('title') else ""
            meta_desc = soup.find('meta', attrs={'name': 'description'})
            h1s = [h1.text for h1 in soup.find_all('h1')]
            
            st.info(f"Keyword in Title: {'✅ Yes' if keyword.lower() in title.lower() else '❌ No'}")
            st.info(f"Keyword in Meta Description: {'✅ Yes' if meta_desc and keyword.lower() in meta_desc.get('content','').lower() else '❌ No'}")
            st.info(f"Keyword in H1 Tags: {'✅ Yes' if any(keyword.lower() in h1.lower() for h1 in h1s) else '❌ No'}")
    else:
        st.info("Enter a target keyword in the sidebar to run a keyword-specific analysis.")

    with st.expander("General On-Page SEO", expanded=True):
        st.success(f"**Title Tag:** {'✅ Present' if soup.find('title') else '❌ Missing!'}")
        st.success(f"**Meta Description:** {'✅ Present' if soup.find('meta', attrs={'name': 'description'}) else '❌ Missing!'}")
        st.success(f"**H1 Tags Found:** {len([h1.text for h1 in soup.find_all('h1')])}")
        st.success(f"**Viewport Meta Tag:** {'✅ Present' if soup.find('meta', attrs={'name': 'viewport'}) else '❌ Missing!'}")

        images = soup.find_all('img')
        images_without_alt = sum(1 for img in images if not img.get('alt', '').strip())
        if images_without_alt == 0:
            st.success("✅ All images have alt attributes.")
        else:
            st.warning(f"⚠️ {images_without_alt} of {len(images)} images are missing alt text.")
    
    with st.expander("Social & Structured Data"):
        og_title = soup.find('meta', property='og:title')
        twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
        json_ld = soup.find('script', type='application/ld+json')
        st.info(f"**Open Graph Tags:** {'✅ Present' if og_title else '⚠️ Missing'}")
        st.info(f"**Twitter Card Tags:** {'✅ Present' if twitter_title else '⚠️ Missing'}")
        st.info(f"**JSON-LD Structured Data:** {'✅ Present' if json_ld else '⚠️ Missing'}")

def display_technical_audit(soup, url):
    st.header("Technical SEO Audit ⚙️", divider="rainbow")
    
    with st.expander("Crawling & Indexing"):
        robots_url = urljoin(url, "/robots.txt")
        try:
            robots_res = requests.get(robots_url, timeout=5)
            if robots_res.status_code == 200:
                st.success("✅ Robots.txt found.")
                st.code(robots_res.text)
            else:
                st.warning("⚠️ Robots.txt not found.")
        except requests.exceptions.RequestException:
            st.error("Could not check for robots.txt.")
            
        canonical_tag = soup.find('link', rel='canonical')
        st.success(f"**Canonical Tag:** {'✅ Present' if canonical_tag else '⚠️ Missing'}")
        if canonical_tag: st.caption(f"Canonical URL: `{canonical_tag.get('href')}`")
        
        hreflang_tags = soup.find_all('link', rel='alternate', hreflang=True)
        st.success(f"**Hreflang Tags:** {'✅ Present' if hreflang_tags else 'ℹ️ Not found (only for multi-language sites)'}")

def display_crawl_results(crawl_data):
    st.header("Site Crawl Overview 🗺️", divider="rainbow")
    if not crawl_data or len(crawl_data) <= 1: 
        st.info("Crawl was not initiated or no additional internal links were found on the homepage."); return
    
    st.markdown(f"Analyzed **{len(crawl_data)}** pages in total.")
    crawl_df_data = [{
        'URL': res.get('url'),
        'Status': res.get('status_code'),
        'Title Present': '✅' if res.get('title') else '❌',
        'Meta Desc. Present': '✅' if res.get('meta_description') else '❌',
        'H1 Count': len(res.get('h1_tags', [])),
        'Error': res.get('error', 'None')
    } for res in crawl_data]
    
    st.dataframe(pd.DataFrame(crawl_df_data), width='stretch', hide_index=True)

# --- Main App Logic ---
def main():
    st.sidebar.title("Configuration")
    url_input = st.sidebar.text_input("Enter Website URL", "https://www.streamlit.io")
    keyword_input = st.sidebar.text_input("Enter Target Keyword (Optional)", key="keyword_input")

    st.sidebar.subheader("Keyword Tools")
    if st.sidebar.button("Suggest Keywords from URL"):
        if url_input:
            url = url_input if url_input.startswith(('http://', 'https://')) else 'https://' + url_input
            with st.spinner("Analyzing text to suggest keywords..."):
                page_data = audit_page(url)
                if page_data and page_data.get('soup'):
                    st.session_state.suggestions = suggest_keywords(page_data['soup'])
                else:
                    st.session_state.suggestions = []
        else:
            st.sidebar.warning("Please enter a URL first.")

    if 'suggestions' in st.session_state and st.session_state.suggestions:
        st.sidebar.info("**Suggested Keywords:** (click to use)")
        for suggestion in st.session_state.suggestions:
            if st.sidebar.button(suggestion, key=f"btn_{suggestion}"):
                st.session_state.keyword_input = suggestion
                st.rerun()

    crawl_pages = st.sidebar.slider("Pages to Crawl (incl. homepage)", 1, 10, 3)

    st.title("🕵️‍♀️ Website Auditor Pro")
    st.markdown(f"### Comprehensive Audit for `{url_input}`")
    
    if st.sidebar.button("🚀 Audit Website", type="primary"):
        url = url_input if url_input.startswith(('http://', 'https://')) else 'https://' + url_input

        with st.spinner(f"Auditing main page: {url}..."):
            main_page_data = audit_page(url)
            if main_page_data.get('error'):
                st.error(f"Failed to audit main page: {main_page_data['error']}"); return
            
            psi_results, psi_error = run_pagespeed_insights(url)
            if psi_error: st.warning(f"Could not get Google PageSpeed data: {psi_error}")

        crawl_data = [main_page_data]
        if crawl_pages > 1 and main_page_data.get('soup'):
            with st.spinner(f"Crawling up to {crawl_pages-1} additional pages..."):
                internal_links = get_internal_links(url, main_page_data['soup'])
                links_to_crawl = list(internal_links - {url})[:crawl_pages-1]
                
                with ThreadPoolExecutor(max_workers=5) as executor:
                    crawl_results = executor.map(audit_page, links_to_crawl)
                crawl_data.extend(list(crawl_results))
        
        st.session_state.audit_ran = True
        st.session_state.main_page_data = main_page_data
        st.session_state.psi_results = psi_results
        st.session_state.crawl_data = crawl_data

    if st.session_state.get('audit_ran'):
        main_page_data = st.session_state.main_page_data
        psi_results = st.session_state.psi_results
        crawl_data = st.session_state.crawl_data
        psi_report = psi_results.get('lighthouseResult', {}) if psi_results else {}
        
        summary_tab, perf_tab, seo_tab, tech_tab, crawl_tab = st.tabs(
            ["Summary", "Performance", "SEO", "Technical", "Site Crawl"]
        )
        
        with summary_tab:
            display_summary(psi_results, main_page_data['soup'])
        with perf_tab:
            display_performance_audit(psi_report)
        with seo_tab:
            display_seo_audit(main_page_data['soup'], st.session_state.keyword_input)
        with tech_tab:
            display_technical_audit(main_page_data['soup'], main_page_data['url'])
        with crawl_tab:
            display_crawl_results(crawl_data)

if __name__ == "__main__":
    main()
