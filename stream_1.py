import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urljoin, urlparse
import textstat
import base64
import io

# --- Configuration and Helpers ---

st.set_page_config(
    page_title="Website Auditor Pro",
    page_icon="🕵️‍♀️",
    layout="wide"
)

# Function to fetch and parse a URL
def get_soup(url):
    """Fetches the URL and returns a BeautifulSoup object."""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()  # Raises an exception for 4XX/5XX errors
        return BeautifulSoup(response.text, 'html.parser'), response.headers, None
    except requests.exceptions.RequestException as e:
        return None, None, str(e)

# Function to run Google PageSpeed Insights API using a secret API key
def run_pagespeed_insights(url):
    """Runs Google PageSpeed Insights and returns the JSON response."""
    # Retrieve the API key from Streamlit secrets
    try:
        api_key = st.secrets["api_keys"]["pagespeed"]
    except KeyError:
        st.error("API key for PageSpeed not found. Please add it to your Streamlit secrets.")
        return None, "Missing API Key"

    # Construct the API URL with the secret key
    api_url = f"https://www.googleapis.com/pagespeedonline/v5/runPagespeed?url={url}&strategy=mobile&category=performance&category=accessibility&category=seo&category=best-practices&key={api_key}"

    try:
        response = requests.get(api_url, timeout=60)
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.RequestException as e:
        # Provide more specific error feedback if it's an API key issue
        if response.status_code == 400:
             return None, f"API Request Failed (Code: 400). This may be due to an invalid API key. Original error: {e}"
        return None, str(e)

# Function to check for broken links (limited scope)
def check_broken_links(soup, base_url):
    """Finds all internal links and checks their status."""
    broken_links = []
    links = soup.find_all('a', href=True)
    internal_links = set()

    for link in links:
        href = link['href']
        joined_url = urljoin(base_url, href)
        # Only check internal links and avoid duplicates
        if urlparse(joined_url).netloc == urlparse(base_url).netloc:
            internal_links.add(joined_url)

    # Limit checks to avoid long run times
    for i, link in enumerate(list(internal_links)[:20]):
        try:
            response = requests.head(link, timeout=5, allow_redirects=True)
            if response.status_code >= 400:
                broken_links.append({'url': link, 'status': response.status_code})
        except requests.exceptions.RequestException:
            broken_links.append({'url': link, 'status': 'Error'})
    return broken_links

# --- UI Display Functions ---

def display_summary(psi_results, soup, headers):
    """Displays the summary tab with scores and key info."""
    st.header("Audit Summary 📝", divider="rainbow")

    if not psi_results:
        st.error("Could not retrieve PageSpeed Insights data.")
        return

    # --- Score Metrics ---
    report = psi_results.get('lighthouseResult', {})
    scores = {
        'Performance': report.get('categories', {}).get('performance', {}).get('score', 0) * 100,
        'Accessibility': report.get('categories', {}).get('accessibility', {}).get('score', 0) * 100,
        'SEO': report.get('categories', {}).get('seo', {}).get('score', 0) * 100,
        'Best Practices': report.get('categories', {}).get('best-practices', {}).get('score', 0) * 100,
    }

    cols = st.columns(4)
    with cols[0]:
        st.metric("Performance", f"{scores['Performance']:.0f}/100")
    with cols[1]:
        st.metric("Accessibility", f"{scores['Accessibility']:.0f}/100")
    with cols[2]:
        st.metric("SEO", f"{scores['SEO']:.0f}/100")
    with cols[3]:
        st.metric("Best Practices", f"{scores['Best Practices']:.0f}/100")

    st.divider()
    left_col, right_col = st.columns(2)

    # --- Mobile Screenshot ---
    with left_col:
        st.subheader("Mobile Viewport")
        screenshot_data = report.get('audits', {}).get('final-screenshot', {}).get('details', {}).get('data')
        if screenshot_data:
            img_bytes = base64.b64decode(screenshot_data.split(',')[1])
            st.image(io.BytesIO(img_bytes), caption="Mobile Screenshot")
        else:
            st.info("Mobile screenshot not available.")

    # --- Basic Info ---
    with right_col:
        st.subheader("Key Information")
        title = soup.find('title').text if soup and soup.find('title') else 'N/A'
        meta_desc = soup.find('meta', attrs={'name': 'description'})
        description = meta_desc['content'] if meta_desc else 'N/A'

        st.info(f"**Title:** {title}")
        st.info(f"**Meta Description:** {description}")
        st.info(f"**Content-Type:** {headers.get('Content-Type', 'N/A')}")
        st.info(f"**Server:** {headers.get('Server', 'N/A')}")


def display_seo_audit(soup, psi_report):
    """Displays the SEO audit tab."""
    st.header("SEO Analysis 🔍", divider="rainbow")
    seo_category = psi_report.get('categories', {}).get('seo', {})
    if not seo_category:
        st.warning("SEO report not available from PageSpeed Insights.")
        return

    st.metric("Overall SEO Score", f"{seo_category.get('score', 0) * 100:.0f}/100")
    st.progress(seo_category.get('score', 0))

    # --- On-Page SEO Checks ---
    st.subheader("On-Page Elements")
    title = soup.find('title')
    h1_tags = [tag.text for tag in soup.find_all('h1')]
    meta_desc = soup.find('meta', attrs={'name': 'description'})

    st.success(f"**Title Tag:** {'Present' if title else 'Missing!'} (`{title.text if title else ''}`)")
    st.success(f"**Meta Description:** {'Present' if meta_desc else 'Missing!'}")
    st.success(f"**H1 Tags Found:** {len(h1_tags)} ({', '.join(h1_tags[:2])}{'...' if len(h1_tags) > 2 else ''})")

    # --- Alt text check ---
    images = soup.find_all('img')
    images_without_alt = [img.get('src') for img in images if not img.get('alt', '').strip()]
    if not images_without_alt:
        st.success("All image tags have alt attributes. ✅")
    else:
        st.warning(f"{len(images_without_alt)} of {len(images)} images are missing descriptive alt text.")
        with st.expander("Show images missing alt text"):
            st.json(images_without_alt)

    # --- Detailed SEO Audits from PSI ---
    st.subheader("Google's SEO Audit Checklist")
    audit_results = []
    for audit_ref in seo_category.get('auditRefs', []):
        audit = psi_report.get('audits', {}).get(audit_ref['id'], {})
        if audit:
            audit_results.append({
                "Check": audit.get('title'),
                "Result": "✅ Passed" if audit.get('score', 0) == 1 else "⚠️ Needs Improvement",
                "Details": audit.get('description')
            })

    st.dataframe(pd.DataFrame(audit_results), use_container_width=True)


def display_performance_audit(psi_report):
    """Displays the Performance and Core Web Vitals tab."""
    st.header("Performance & Core Web Vitals ⚡", divider="rainbow")
    perf_category = psi_report.get('categories', {}).get('performance', {})
    if not perf_category:
        st.warning("Performance report not available.")
        return

    st.metric("Overall Performance Score", f"{perf_category.get('score', 0) * 100:.0f}/100")
    st.progress(perf_category.get('score', 0))

    # --- Core Web Vitals ---
    st.subheader("Core Web Vitals")
    metrics = {
        'largest-contentful-paint': "Largest Contentful Paint (LCP)",
        'first-contentful-paint': "First Contentful Paint (FCP)",
        'cumulative-layout-shift': "Cumulative Layout Shift (CLS)",
        'total-blocking-time': "Total Blocking Time (TBT)",
    }
    metric_data = []
    for key, name in metrics.items():
        metric_value = psi_report.get('audits', {}).get(key, {})
        metric_data.append({
            "Metric": name,
            "Value": metric_value.get('displayValue', 'N/A'),
            "Score": f"{metric_value.get('score', 0) * 100:.0f}/100"
        })
    st.dataframe(pd.DataFrame(metric_data), use_container_width=True)

    # --- Performance Opportunities ---
    st.subheader("Key Opportunities for Improvement")
    opportunities = []
    for audit_ref in perf_category.get('auditRefs', []):
        audit = psi_report.get('audits', {}).get(audit_ref['id'], {})
        # Show only audits that are opportunities (i.e., failed or have potential savings)
        if audit and audit.get('score', 1) < 0.9 and 'details' in audit:
            opportunities.append({
                "Opportunity": audit.get('title'),
                "Potential Savings": audit.get('details', {}).get('overallSavingsMs', 0)
            })

    if opportunities:
        df_opps = pd.DataFrame(opportunities)
        df_opps = df_opps[df_opps['Potential Savings'] > 0]
        df_opps = df_opps.sort_values(by='Potential Savings', ascending=False)
        st.dataframe(df_opps, use_container_width=True, hide_index=True)
    else:
        st.success("Great job! No major performance opportunities detected.")


def display_accessibility_audit(psi_report):
    """Displays the accessibility audit tab."""
    st.header("Accessibility Audit ♿", divider="rainbow")
    acc_category = psi_report.get('categories', {}).get('accessibility', {})
    if not acc_category:
        st.warning("Accessibility report not available.")
        return

    st.metric("Overall Accessibility Score", f"{acc_category.get('score', 0) * 100:.0f}/100")
    st.progress(acc_category.get('score', 0))

    st.subheader("Accessibility Checklist (WCAG)")
    failed_audits = []
    for audit_ref in acc_category.get('auditRefs', []):
        audit = psi_report.get('audits', {}).get(audit_ref['id'], {})
        if audit and audit.get('score') is not None and audit.get('score') < 1:
            failed_audits.append({
                "Issue": audit.get('title'),
                "Description": audit.get('description'),
                "Help": audit.get('helpText', 'No additional help text.')
            })

    if failed_audits:
        st.warning(f"Found {len(failed_audits)} accessibility issues.")
        for issue in failed_audits:
            with st.expander(f"**Issue:** {issue['Issue']}"):
                st.markdown(issue['Description'])
    else:
        st.success("Fantastic! No major accessibility issues were detected.")


def display_technical_audit(soup, headers, url, broken_links):
    """Displays the technical and content audit tab."""
    st.header("Technical & Content Audit ⚙️", divider="rainbow")

    # --- Security ---
    st.subheader("Security")
    security_headers = {
        'Content-Security-Policy': headers.get('Content-Security-Policy'),
        'X-Frame-Options': headers.get('X-Frame-Options'),
        'X-Content-Type-Options': headers.get('X-Content-Type-Options'),
    }
    st.info(f"**HTTPS:** {'✅ Active' if url.startswith('https') else '❌ Not secure!'}")
    for header, value in security_headers.items():
        if value:
            st.success(f"**{header}:** Present")
        else:
            st.warning(f"**{header}:** Missing")

    # --- Robots.txt and Sitemap ---
    st.subheader("Crawling and Indexing")
    try:
        robots_url = urljoin(url, "/robots.txt")
        robots_res = requests.get(robots_url, timeout=5)
        st.info(f"**Robots.txt:** {'Found' if robots_res.status_code == 200 else 'Not Found'} at `{robots_url}`")

        sitemap_url = urljoin(url, "/sitemap.xml")
        sitemap_res = requests.head(sitemap_url, timeout=5)
        st.info(f"**Sitemap.xml:** {'Found' if sitemap_res.status_code == 200 else 'Not Found'} at `{sitemap_url}`")
    except requests.exceptions.RequestException:
        st.error("Could not check for robots.txt or sitemap.xml.")

    # --- Content Readability ---
    st.subheader("Content Readability")
    page_text = soup.get_text()
    if page_text:
        readability_score = textstat.flesch_reading_ease(page_text)
        st.metric("Flesch Reading Ease Score", f"{readability_score:.2f}")
        st.caption("Score of 60-70 is considered easily understandable by 13-15 year olds. Higher is easier.")
    else:
        st.info("Could not extract text for readability analysis.")

    # --- Broken Links ---
    st.subheader("Broken Link Checker (Sample)")
    if broken_links:
        st.warning(f"Found {len(broken_links)} broken links on the homepage (from a sample of 20).")
        st.dataframe(pd.DataFrame(broken_links), use_container_width=True)
    else:
        st.success("No broken internal links found in the homepage sample. ✅")

# --- Main App Logic ---

def main():
    """Main function to run the Streamlit app."""
    st.title("🕵️‍♀️ Website Auditor Pro")
    st.markdown("Enter a website URL to perform a comprehensive audit covering Performance, SEO, Accessibility, and more.")

    url_input = st.text_input("Enter Website URL", "https://www.streamlit.io", help="Enter the full URL (e.g., https://www.example.com)")

    if st.button("🚀 Audit Website", type="primary"):
        if not url_input:
            st.warning("Please enter a URL to audit.")
            return

        # Validate and format URL
        if not url_input.startswith(('http://', 'https://')):
            url = 'https://' + url_input
        else:
            url = url_input

        with st.spinner(f"Auditing {url}... This may take a minute..."):
            # Run all analyses
            soup, headers, html_error = get_soup(url)
            psi_results, psi_error = run_pagespeed_insights(url)

            # Handle major errors
            if html_error:
                st.error(f"Failed to fetch the website: {html_error}")
                return
            if psi_error:
                st.error(f"Failed to get Google PageSpeed Insights data: {psi_error}")
                # We can still proceed with the HTML analysis
            if not soup:
                 st.error("Could not parse the website's HTML.")
                 return


            # Run analyses that depend on soup
            broken_links = check_broken_links(soup, url)
            psi_report = psi_results.get('lighthouseResult', {}) if psi_results else {}

            # --- Display Results in Tabs ---
            tab_summary, tab_perf, tab_seo, tab_access, tab_tech = st.tabs([
                "Summary", "Performance", "SEO", "Accessibility", "Technical & Content"
            ])

            with tab_summary:
                display_summary(psi_results, soup, headers)

            with tab_perf:
                display_performance_audit(psi_report)

            with tab_seo:
                display_seo_audit(soup, psi_report)

            with tab_access:
                display_accessibility_audit(psi_report)

            with tab_tech:
                display_technical_audit(soup, headers, url, broken_links)

if __name__ == "__main__":
    main()
