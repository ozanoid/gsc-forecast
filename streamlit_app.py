import pandas as pd
import streamlit as st
import matplotlib.pyplot as plt
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import datetime
from dateutil.relativedelta import relativedelta
import os
from requests_oauthlib import OAuth2Session
import json

# Streamlit başlık
st.title('SEO Forecasting Tool with Google Search Console Integrationz')

# Google OAuth ve API kurulumu
CLIENT_CONFIG = {
    "web": {
        "client_id": os.environ.get("GOOGLE_CLIENT_ID"),
        "project_id": os.environ.get("GOOGLE_PROJECT_ID"),
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
        "client_secret": os.environ.get("GOOGLE_CLIENT_SECRET"),
        "redirect_uris": [os.environ.get("REDIRECT_URI")]
    }
}

SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']

# Yardımcı fonksiyonlar
def round_position(position):
    return int(position + 0.4) if position <= 20.4 else int(position)

def clean_data(data):
    for col in ['Clicks', 'Impressions', 'CTR', 'Position']:
        data[col] = data[col].astype(float)
    return data

def create_ctr_map(data):
    data['Rounded Pos.'] = data['Position'].apply(round_position)
    return data.groupby('Rounded Pos.').apply(
        lambda x: pd.Series({
            'Total_Clicks': x['Clicks'].sum(),
            'Total_Impressions': x['Impressions'].sum(),
            'Calculated_CTR': x['Clicks'].sum() / x['Impressions'].sum() if x['Impressions'].sum() > 0 else 0
        })
    ).reset_index()

def get_target_positions(period):
    if f'targets_{period}' not in st.session_state:
        st.session_state[f'targets_{period}'] = {
            'Top 3': 3, 'Top 3.1-5': 5, 'Top 5.1-7': 7,
            'Top 7.1-10': 10, 'Top 10.1-15': 15, 'Top 15.1-20': 20
        }
    
    targets = {}
    for group in ['Top 3', 'Top 3.1-5', 'Top 5.1-7', 'Top 7.1-10', 'Top 10.1-15', 'Top 15.1-20']:
        key = f"{period}_{group}_target"
        targets[group] = st.number_input(
            f"{period} - {group} için hedef pozisyonu girin (1-20): ",
            min_value=1, max_value=20,
            value=st.session_state[f'targets_{period}'][group],
            key=key, on_change=update_target,
            args=(period, group, key)
        )
    return targets

def calculate_target_ctr(data, ctr_map, targets):
    def get_target(pos):
        if pos <= 3: return targets['Top 3']
        elif pos <= 5: return targets['Top 3.1-5']
        elif pos <= 7: return targets['Top 5.1-7']
        elif pos <= 10: return targets['Top 7.1-10']
        elif pos <= 15: return targets['Top 10.1-15']
        elif pos <= 20: return targets['Top 15.1-20']
        else: return 0

    data['Target'] = data['Position'].apply(get_target)
    data['Target CTR'] = data['Target'].apply(
        lambda pos: ctr_map[ctr_map['Rounded Pos.'] == pos]['Calculated_CTR'].values[0] if pos in ctr_map['Rounded Pos.'].values else 0
    )
    data['Target Clicks'] = data['Impressions'] * data['Target CTR']
    data['Positive Difference'] = data.apply(lambda row: max(0, row['Target Clicks'] - row['Clicks']), axis=1)
    return data

def calculate_dates():
    today = datetime.date.today()
    
    # Başlangıç tarihi: geçen yılın bir önceki ayının ilk günü
    start_date = (today.replace(day=1) - relativedelta(months=1)).replace(year=today.year - 1)
    
    # Bitiş tarihi: başlangıç tarihinden 12 ay sonraki ayın son günü
    end_date = (start_date + relativedelta(months=12)) - relativedelta(days=1)
    
    return start_date, end_date

def calculate_period_dates(start_date, end_date):
    total_months = 12  # Toplam süre her zaman 12 ay olacak
    period_length = total_months // 4
    return {
        f'P{i+1}': (
            start_date + relativedelta(months=i*period_length),
            start_date + relativedelta(months=(i+1)*period_length) - relativedelta(days=1)
        ) for i in range(4)
    }

def get_brand_keywords():
    brand_keywords = st.text_input("Enter brand keywords (comma-separated):")
    return [keyword.strip().lower() for keyword in brand_keywords.split(',')] if brand_keywords else []

@st.cache_data
def fetch_gsc_data(property_url, start_date, end_date, _credentials, brand_keywords):
    service = build('searchconsole', 'v1', credentials=_credentials)
    
    keyword_filters = [
        {
            "dimension": "query",
            "operator": "notContains",
            "expression": keyword
        } for keyword in brand_keywords
    ]
    
    request = {
        'startDate': start_date.isoformat(),
        'endDate': end_date.isoformat(),
        'dimensions': ['query'],
        'rowLimit': 25000,
        'dimensionFilterGroups': [
            {
                "groupType": "and",
                "filters": keyword_filters
            }
        ] if keyword_filters else []
    }
    
    response = service.searchanalytics().query(siteUrl=property_url, body=request).execute()
    rows = response.get('rows', [])
    
    return pd.DataFrame([
        {
            'Query': row['keys'][0],
            'Clicks': row['clicks'],
            'Impressions': row['impressions'],
            'CTR': row['ctr'],
            'Position': row['position']
        } for row in rows
    ])

# Yardımcı fonksiyonlar
def update_target(period, group, key):
    st.session_state[f'targets_{period}'][group] = st.session_state[key]

def on_site_change():
    st.session_state.selected_site = st.session_state.site_selector

# Token işlemleri için yardımcı fonksiyonlar
def token_saver(token):
    st.session_state.token = token

# OAuth akışı
def run_oauth_flow():
    client_config = CLIENT_CONFIG['web']
    flow = Flow.from_client_config(
        client_config=CLIENT_CONFIG,
        scopes=SCOPES,
        redirect_uri="https://gsc-forecast-whn6zxuvo86sua5yp8kp6h.streamlit.app/"
    )
    
    if 'token' not in st.session_state:
        if 'code' not in st.query_params:
            authorization_url, _ = flow.authorization_url(prompt='consent')
            st.markdown(f"[Click here to authorize]({authorization_url})")
        else:
            flow.fetch_token(code=st.query_params['code'])
            st.session_state.token = flow.credentials.to_json()
            st.experimental_rerun()
    
    if 'token' in st.session_state:
        return Credentials.from_authorized_user_info(json.loads(st.session_state.token))
    
    return None

# Ana uygulama
def main():
    credentials = run_oauth_flow()
    
    if credentials:
        if 'site_urls' not in st.session_state:
            service = build('searchconsole', 'v1', credentials=credentials)
            sites = service.sites().list().execute()
            st.session_state.site_urls = [site['siteUrl'] for site in sites['siteEntry']]
        
        if 'selected_site' not in st.session_state:
            st.session_state.selected_site = st.session_state.site_urls[0] if st.session_state.site_urls else None

        # Arama kutusu ve site seçimi
        search_term = st.text_input("Search for a site:", "")
        filtered_sites = [site for site in st.session_state.site_urls if search_term.lower() in site.lower()]
        selected_site = st.selectbox(
            "Select a property:",
            filtered_sites,
            index=0 if filtered_sites else None,
            key='site_selector'
        )
        if selected_site:
            st.session_state.selected_site = selected_site

        # Tarih hesaplamaları ve dönem hedefleri
        start_date, end_date = calculate_dates()
        st.write(f"Analiz dönemi: {start_date.strftime('%Y-%m-%d')} - {end_date.strftime('%Y-%m-%d')}")
        st.markdown(f"Seçili site: `{st.session_state.selected_site}`")
        
        periods = calculate_period_dates(start_date, end_date)
        for period, (period_start, period_end) in periods.items():
            st.subheader(f"{period} Dönemi Hedef Pozisyonları ({period_start.strftime('%Y-%m-%d')} - {period_end.strftime('%Y-%m-%d')})")
            get_target_positions(period)
        
        brand_keywords = get_brand_keywords()
        
        if st.button("Fetch Data and Analyze"):
            gsc_data = fetch_gsc_data(st.session_state.selected_site, start_date, end_date, credentials, brand_keywords)
            st.write("Fetched GSC Data (excluding brand keywords):")
            st.write(gsc_data)
            
            ctr_map = create_ctr_map(gsc_data)
            st.write("CTR Haritası:")
            st.write(ctr_map)
            
            results = {}
            for period, (period_start, period_end) in periods.items():
                st.subheader(f"{period} Dönemi ({period_start} - {period_end})")
                
                period_data = fetch_gsc_data(st.session_state.selected_site, period_start, period_end, credentials, brand_keywords)
                st.write(f"{period} için çekilen veri:")
                st.write(period_data)
                
                targets = st.session_state[f'targets_{period}']
                
                period_results = calculate_target_ctr(period_data, ctr_map, targets)
                results[period] = period_results
                
                st.write(f"{period} Analiz Sonuçları:")
                st.write(period_results)
            
            st.header("Özet Ekranı")
            total_additional_traffic = sum(result['Positive Difference'].sum() for result in results.values())
            st.metric("Toplam Ek Trafik", value=total_additional_traffic)
            
            period_traffic = {period: result['Positive Difference'].sum() for period, result in results.items()}
            fig, ax = plt.subplots()
            ax.bar(period_traffic.keys(), period_traffic.values())
            ax.set_ylabel('Ek Trafik')
            ax.set_title('Dönemlere Göre Ek Trafik')
            st.pyplot(fig)
            
            for period, result in results.items():
                csv = result.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label=f"{period} Sonuçlarını İndir",
                    data=csv,
                    file_name=f'{period}_results.csv',
                    mime='text/csv',
                    key=f"download_{period}"
                )

    else:
        st.write("Please authorize the application to continue.")

if __name__ == "__main__":
    main()
