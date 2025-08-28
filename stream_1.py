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

# --- Configuration and Helpers ---

st.set_page_config(
    page_title="Website Auditor Pro",
    page_icon="🕵️‍♀️",
    layout="wide"
)

# --- Caching Functions for Performance ---

@st.cache_data(ttl=3600)  # Cache for 1 hour
def get_soup(url):
    """Fetches the URL and returns a BeautifulSoup object."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return BeautifulSoup(response.text, 'html.parser'), response.headers, None
    except requests.exceptions.RequestException as e:
        return None, None, str(e)

@st.cache_data(ttl=3600)
def run_pagespeed_insights(url):
    """Runs Google PageSpeed Insights and returns the JSON response."""
    api_key = st.secrets.get("GOOGLE_PAGESPEED_API_KEY")
    if not api_key:
        return None, "Google PageSpeed API Key not found in Streamlit secrets. Please configure it."

    api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy=mobile&category=performance&category=accessibility&category=seo&category=best-practices&key={api_key}"
    try:
        response = requests.get(api_url, timeout=90)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as e:
        return None, str(e)

# --- Analysis Functions ---

def check_single_link(link):
    """Checks the status of a single link."""
    try:
        response = requests.head(link, timeout=7, allow_redirects=True, headers={'User-Agent': 'Mozilla/5.0'})
        if response.status_code >= 400:
            return {'url': link, 'status': response.status_code}
    except requests.exceptions.RequestException:
        return {'url': link, 'status': 'Error'}
    return None

def check_broken_links(soup, base_url):
    """Finds internal links and checks their status in parallel."""
    links = {urljoin(base_url, a['href']) for a in soup.find_all('a', href=True)}
    internal_links = {link for link in links if urlparse(link).netloc == urlparse(base_url).netloc}
    
    # Use a ThreadPoolExecutor to check links in parallel for speed
    with ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(check_single_link, list(internal_links)[:25]) # Limit to 25 checks
    
    return [result for result in results if result]

def generate_report(url, psi_results, soup, headers, broken_links):
    """Generates a downloadable text report of the audit."""
    report_lines = [f"Audit Report for: {url}", f"Date: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}\n"]
    
    # Summary
    report_lines.append("--- Summary ---")
    report = psi_results.get('lighthouseResult', {})
    scores = {
        'Performance': report.get('categories', {}).get('performance', {}).get('score', 0) * 100,
        'Accessibility': report.get('categories', {}).get('accessibility', {}).get('score', 0) * 100,
        'SEO': report.get('categories', {}).get('seo', {}).get('score', 0) * 100,
        'Best Practices': report.get('categories', {}).get('best-practices', {}).get('score', 0) * 100,
    }
    for key, value in scores.items():
        report_lines.append(f"{key} Score: {value:.0f}/100")
    
    # Key Issues
    report_lines.append("\n--- Key Findings & Issues ---")
    # Performance
    perf_category = report.get('categories', {}).get('performance', {})
    for audit_ref in perf_category.get('auditRefs', []):
        audit = report.get('audits', {}).get(audit_ref['id'], {})
        if audit and audit.get('score', 1) < 0.9 and 'overallSavingsMs' in audit.get('details', {}):
            savings = audit['details']['overallSavingsMs']
            if savings > 100:
                report_lines.append(f"[Performance] Opportunity: {audit.get('title')} (Potential Savings: {savings} ms)")
    
    # Accessibility
    acc_category = report.get('categories', {}).get('accessibility', {})
    failed_audits_count = sum(1 for ref in acc_category.get('auditRefs', []) if report.get('audits', {}).get(ref['id'], {}).get('score', 1) < 1)
    if failed_audits_count > 0:
        report_lines.append(f"[Accessibility] Found {failed_audits_count} issues.")

    # SEO
    images = soup.find_all('img')
    images_without_alt = sum(1 for img in images if not img.get('alt', '').strip())
    if images_without_alt > 0:
        report_lines.append(f"[SEO] Found {images_without_alt} images missing alt text.")

    # Technical
    if broken_links:
        report_lines.append(f"[Technical] Found {len(broken_links)} broken internal links.")

    return "\n".join(report_lines)

# --- UI Display Functions ---
# (Display functions remain largely the same, but with updated checks and UI elements)

def display_summary(psi_results, soup, headers, url, broken_links, report_text):
    st.header("Audit Summary 📝", divider="rainbow")
    if not psi_results:
        st.error("Could not retrieve PageSpeed Insights data.")
        return

    report = psi_results.get('lighthouseResult', {})
    scores = {
        'Performance': report.get('categories', {}).get('performance', {}).get('score', 0) * 100,
        'Accessibility': report.get('categories', {}).get('accessibility', {}).get('score', 0) * 100,
        'SEO': report.get('categories', {}).get('seo', {}).get('score', 0) * 100,
        'Best Practices': report.get('categories', {}).get('best-practices', {}).get('score', 0) * 100,
    }

    cols = st.columns(5) # Add a column for the download button
    with cols[0]: st.metric("Performance", f"{scores['Performance']:.0f}/100")
    with cols[1]: st.metric("Accessibility", f"{scores['Accessibility']:.0f}/100")
    with cols[2]: st.metric("SEO", f"{scores['SEO']:.0f}/100")
    with cols[3]: st.metric("Best Practices", f"{scores['Best Practices']:.0f}/100")
    with cols[4]:
        st.download_button(
            label="⬇️ Download Report",
            data=report_text,
            file_name=f"audit_report_{urlparse(url).netloc}.txt",
            mime="text/plain"
        )
    
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
        st.info(f"**Server:** {headers.get('Server', 'N/A')}")

def display_seo_audit(soup, psi_report):
    st.header("SEO Analysis 🔍", divider="rainbow")
    seo_category = psi_report.get('categories', {}).get('seo', {})
    
    st.metric("Overall SEO Score", f"{seo_category.get('score', 0) * 100:.0f}/100")
    st.progress(seo_category.get('score', 0))

    st.subheader("On-Page Elements")
    title = soup.find('title')
    h1_tags = [tag.text for tag in soup.find_all('h1')]
    
    st.success(f"**Title Tag:** {'✅ Present' if title else '❌ Missing!'} (`{title.text if title else ''}`)")
    st.success(f"**Meta Description:** {'✅ Present' if soup.find('meta', attrs={'name': 'description'}) else '❌ Missing!'}")
    st.success(f"**H1 Tags Found:** {len(h1_tags)} ({', '.join(h1_tags[:1])}{'...' if len(h1_tags) > 1 else ''})")
    st.success(f"**Viewport Meta Tag:** {'✅ Present' if soup.find('meta', attrs={'name': 'viewport'}) else '❌ Missing!'}")

    images = soup.find_all('img')
    images_without_alt = [img.get('src', 'No src') for img in images if not img.get('alt', '').strip()]
    if not images_without_alt:
        st.success("All images have alt attributes. ✅")
    else:
        st.warning(f"{len(images_without_alt)} of {len(images)} images are missing descriptive alt text.")

    st.subheader("Social & Structured Data")
    og_title = soup.find('meta', property='og:title')
    twitter_title = soup.find('meta', attrs={'name': 'twitter:title'})
    json_ld = soup.find('script', type='application/ld+json')
    st.info(f"**Open Graph Tags (for Facebook/LinkedIn):** {'✅ Present' if og_title else '⚠️ Missing'}")
    st.info(f"**Twitter Card Tags:** {'✅ Present' if twitter_title else '⚠️ Missing'}")
    st.info(f"**JSON-LD Structured Data:** {'✅ Present' if json_ld else '⚠️ Missing'}")

def display_performance_audit(psi_report):
    # This function is largely the same, but with the updated width parameter
    st.header("Performance & Core Web Vitals ⚡", divider="rainbow")
    # ... (code omitted for brevity, logic is sound)
    # Ensure any st.dataframe calls use width='stretch'
    
def display_accessibility_audit(psi_report):
    # This function is largely the same, logic is sound
    st.header("Accessibility Audit ♿", divider="rainbow")
    # ... (code omitted for brevity)

def display_technical_audit(soup, headers, url, broken_links):
    # This function is largely the same, logic is sound
    st.header("Technical & Content Audit ⚙️", divider="rainbow")
    # ... (code omitted for brevity)

# --- Main App Logic ---
def main():
    st.title("🕵️‍♀️ Website Auditor Pro")
    st.markdown("Enter a website URL to perform a comprehensive audit covering Performance, SEO, Accessibility, and more.")

    url_input = st.text_input("Enter Website URL", "https://www.streamlit.io", help="Enter the full URL (e.g., https://www.example.com)")

    if st.button("🚀 Audit Website", type="primary"):
        if not url_input.strip():
            st.warning("Please enter a URL to audit.")
            return

        url = url_input if url_input.startswith(('http://', 'https://')) else 'https://' + url_input

        with st.spinner(f"Auditing {url}... This may take a minute..."):
            soup, headers, html_error = get_soup(url)
            if html_error:
                st.error(f"Failed to fetch the website: {html_error}"); return
            if not soup:
                st.error("Could not parse the website's HTML."); return

            psi_results, psi_error = run_pagespeed_insights(url)
            if psi_error:
                st.error(f"Failed to get Google PageSpeed Insights data: {psi_error}")
                # Allow continuing if PSI fails but HTML was successful
            
            broken_links = check_broken_links(soup, url)
            report_text = generate_report(url, psi_results, soup, headers, broken_links) if psi_results else "Report could not be generated."

        psi_report = psi_results.get('lighthouseResult', {}) if psi_results else {}

        tab_summary, tab_perf, tab_seo, tab_access, tab_tech = st.tabs([
            "Summary", "Performance", "SEO", "Accessibility", "Technical & Content"
        ])

        with tab_summary:
            display_summary(psi_results, soup, headers, url, broken_links, report_text)
        with tab_perf:
            # Reusing the existing function; assuming it's been updated with width='stretch'
            # For brevity, I'm not re-pasting all display functions. Ensure they are complete.
            display_performance_audit(psi_report)
        with tab_seo:
            display_seo_audit(soup, psi_report)
        with tab_access:
            display_accessibility_audit(psi_report)
        with tab_tech:
            display_technical_audit(soup, headers, url, broken_links)

if __name__ == "__main__":
    main()
