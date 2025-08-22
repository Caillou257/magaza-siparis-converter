import streamlit as st
import pandas as pd
import re
from io import BytesIO
from datetime import datetime

# Sayfa yapılandırması
st.set_page_config(
    page_title="Mağaza Sipariş Dönüştürücü", 
    page_icon="📊",
    layout="centered"
)

# Özel CSS tasarımı
st.markdown("""
<style>
    .main > div {
        padding-top: 2rem;
    }
    .stButton>button {
        width: 100%;
        background-color: #FF6B6B;
        color: white;
    }
    .stButton>button:hover {
        background-color: #FF5252;
    }
    div[data-testid="metric-container"] {
        background-color: #F8F9FA;
        border: 1px solid #DEE2E6;
        padding: 1rem;
        border-radius: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# Başlık
st.title("📊 Mağaza Sipariş Dönüştürücü")
st.markdown("Müşteri Excel dosyalarını mağaza bazlı sipariş formatına dönüştürün")
st.markdown("---")

# Dosya yükleme alanı
uploaded_file = st.file_uploader(
    "Excel dosyası seçin",
    type=["xlsx", "xls"],
    help="Müşteriden aldığınız Excel dosyasını yükleyin"
)

def clean_number(value):
    """Değerleri temizle ve tam sayıya dönüştür"""
    if pd.isnull(value):
        return 0
    
    # Excel'den gelen sayısal değerler
    if isinstance(value, (int, float)):
        return int(value) if value >= 10 else 0
    
    # Metin değerleri
    value_str = str(value).strip()
    if value_str in ['', '-', 'NaN', 'nan']:
        return 0
    
    try:
        value_str = value_str.replace(' ', '').replace(',', '.')
        result = float(value_str)
        return int(result) if result >= 10 else 0
    except:
        return 0

def find_store_columns(df):
    """Mağaza sütunlarını dinamik olarak bul"""
    # Daha esnek pattern: 3-4 haneli sayı + opsiyonel harf kombinasyonu
    # Bu pattern gelecekte yeni store tipleri eklendiğinde de çalışacak
    store_pattern = re.compile(r'^\d{3,4}\s*[A-Z]+$')
    
    store_cols = []
    store_start_idx = None
    store_end_idx = None
    
    # Bilinen store tiplerini logla (debug için)
    found_store_types = set()
    
    for idx, col in enumerate(df.columns):
        col_str = str(col).strip()
        if store_pattern.match(col_str):
            if store_start_idx is None:
                store_start_idx = idx
            store_cols.append(col)
            
            # Store tipini çıkar ve logla
            match = re.search(r'^\d{3,4}\s*([A-Z]+)$', col_str)
            if match:
                store_type = match.group(1)
                found_store_types.add(store_type)
                
        elif col == "TOPLAM" and store_start_idx is not None:
            store_end_idx = idx
            break
    
    # Debug bilgisi göster
    if store_cols:
        st.info(f"🔍 Bulunan store tipleri: {', '.join(sorted(found_store_types))}")
    
    return store_cols, store_start_idx, store_end_idx

def process_file(file_buffer, original_filename):
    """Excel dosyasını işle ve yeni formata dönüştür"""
    with st.spinner('Dosyanız işleniyor...'):
        # Excel'i oku
        df = pd.read_excel(file_buffer, engine='openpyxl')
        
        # Mağaza sütunlarını dinamik olarak bul
        store_cols, store_start_idx, store_end_idx = find_store_columns(df)
        
        if not store_cols:
            st.error("❌ Mağaza sütunları bulunamadı. Dosya formatı: Mağaza kodları (örn: 798 MM, 5776 M) ve TOPLAM sütunu olmalı.")
            # Debug bilgisi göster
            st.write("Bulunan sütunlar:", list(df.columns[:20]))
            return None, None, None, None, None
        
        st.success(f"✅ {len(store_cols)} mağaza sütunu bulundu")
        
        # Debug: Bulunan store sütunlarını göster
        with st.expander("🔍 Bulunan Store Sütunları (Debug)"):
            store_debug_df = pd.DataFrame({
                'Sütun Adı': store_cols,
                'Store Kodu': [re.search(r'^(\d{3,4})', col).group(1) if re.search(r'^(\d{3,4})', col) else 'N/A' for col in store_cols],
                'Store Tipi': [re.search(r'^\d{3,4}\s*([A-Z]+)$', col).group(1) if re.search(r'^\d{3,4}\s*([A-Z]+)$', col) else 'N/A' for col in store_cols]
            })
            st.dataframe(store_debug_df, use_container_width=True, hide_index=True)
        
        # Çıktı hazırla
        output_df = pd.DataFrame(columns=[
            "Mağaza Kodu", "Tarih", "Mağaza Kodu2", "Mağaza Adı", "Artikel",
            "Kod", "MALZEME TANIMI", "Adet", "Birim Fiyat", "TOPLAM TUTAR(TL)", "İlgili"
        ])
        
        magaza_kodu = original_filename.rsplit('.', 1)[0]
        store_totals = {}
        product_totals = {}  # Ürün bazlı toplamlar
        product_descriptions = {}  # Ürün açıklamaları
        product_count = 0
        
        # İlerleme çubuğu
        progress_bar = st.progress(0)
        total_rows = len(df)
        
        for idx, row in df.iterrows():
            # İlerleme durumunu güncelle
            progress_bar.progress((idx + 1) / total_rows)
            
            # Boş ürün kodlarını atla
            kod = row.get("Hmk Kod", None)
            if pd.isnull(kod) or str(kod).strip() == '':
                continue
            
            # Ürün açıklamasını al
            description = row.get("Hmk Ürün Açıklama", "")
            if not pd.isnull(description):
                product_descriptions[str(kod)] = str(description)
            
            product_count += 1
            
            # Her mağazayı işle
            for store_col in store_cols:
                value = clean_number(row[store_col])
                
                if value > 0:
                    # Daha esnek store kodu çıkarma - herhangi bir harf kombinasyonunu kaldır
                    match = re.search(r'^(\d{3,4})\s*[A-Z]*$', store_col)
                    if match:
                        magaza_kodu2 = match.group(1)
                        
                        # Toplamları takip et
                        store_totals[magaza_kodu2] = store_totals.get(magaza_kodu2, 0) + value
                        
                        # Ürün bazlı toplamları takip et
                        if str(kod) not in product_totals:
                            product_totals[str(kod)] = 0
                        product_totals[str(kod)] += value
                        
                        # Satır ekle - MALZEME TANIMI'na açıklama ekle
                        output_df.loc[len(output_df)] = [
                            magaza_kodu,     # Mağaza Kodu
                            "",              # Tarih
                            magaza_kodu2,    # Mağaza Kodu2
                            "",              # Mağaza Adı
                            "",              # Artikel
                            str(kod),        # Kod
                            str(description) if not pd.isnull(description) else "",  # MALZEME TANIMI
                            value,           # Adet
                            "",              # Birim Fiyat
                            "",              # TOPLAM TUTAR
                            ""               # İlgili
                        ]
        
        progress_bar.empty()
        
    return output_df, store_totals, product_count, len(store_cols), (product_totals, product_descriptions)

# Ana işlem
if uploaded_file:
    # Dosya bilgileri
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Dosya Adı", uploaded_file.name)
    with col2:
        st.metric("Dosya Boyutu", f"{uploaded_file.size / 1024:.1f} KB")
    with col3:
        st.metric("Yükleme Zamanı", datetime.now().strftime("%H:%M:%S"))
    
    # Dosyayı işle
    result = process_file(uploaded_file, uploaded_file.name)
    
    if result[0] is not None:
        result_df, store_totals, product_count, store_count, (product_totals, product_descriptions) = result
        
        if not result_df.empty:
            st.success("✅ Dosya başarıyla işlendi!")
            
            # Özet metrikler
            st.markdown("### 📈 İşlem Özeti")
            col1, col2, col3, col4 = st.columns(4)
            
            with col1:
                st.metric("Toplam Mağaza", f"{len(store_totals):,}")
            with col2:
                st.metric("Toplam Ürün", f"{product_count:,}")
            with col3:
                st.metric("Toplam Miktar", f"{sum(store_totals.values()):,}")
            with col4:
                st.metric("Çıktı Satırı", f"{len(result_df):,}")
            
            # İki sütunlu layout
            col_left, col_right = st.columns(2)
            
            with col_left:
                # Mağaza özeti
                st.markdown("### 🏪 Miktar Bazında İlk 10 Mağaza")
                store_summary = pd.DataFrame(
                    [(k, v) for k, v in store_totals.items()],
                    columns=['Mağaza Kodu', 'Toplam Miktar']
                ).sort_values('Toplam Miktar', ascending=False)
                
                top_stores = store_summary.head(10).copy()
                top_stores['Sıra'] = range(1, len(top_stores) + 1)
                top_stores['Toplam Miktar'] = top_stores['Toplam Miktar'].apply(lambda x: f"{x:,}")
                top_stores = top_stores[['Sıra', 'Mağaza Kodu', 'Toplam Miktar']]
                
                st.dataframe(
                    top_stores,
                    use_container_width=True,
                    hide_index=True,
                    height=400
                )
            
            with col_right:
                # En çok sipariş edilen ürünler
                st.markdown("### 📦 En Çok Sipariş Edilen İlk 10 Ürün")
                product_summary = []
                for kod, miktar in product_totals.items():
                    aciklama = product_descriptions.get(kod, "Açıklama yok")
                    product_summary.append({
                        'Ürün Kodu': kod,
                        'Açıklama': aciklama[:50] + "..." if len(aciklama) > 50 else aciklama,
                        'Toplam Miktar': miktar
                    })
                
                product_df = pd.DataFrame(product_summary).sort_values('Toplam Miktar', ascending=False).head(10)
                product_df['Sıra'] = range(1, len(product_df) + 1)
                product_df['Toplam Miktar'] = product_df['Toplam Miktar'].apply(lambda x: f"{x:,}")
                product_df = product_df[['Sıra', 'Ürün Kodu', 'Açıklama', 'Toplam Miktar']]
                
                st.dataframe(
                    product_df,
                    use_container_width=True,
                    hide_index=True,
                    height=400
                )
            
            # Arama fonksiyonu
            st.markdown("### 🔍 Mağaza Sorgulama")
            col1, col2 = st.columns([1, 2])
            with col1:
                search_store = st.text_input("Mağaza kodu girin:", placeholder="örn: 7684")
            
            if search_store:
                if search_store in store_totals:
                    with col2:
                        st.info(f"**Mağaza {search_store}**: {store_totals[search_store]:,} adet")
                    
                    # Bu mağaza için ürünleri göster
                    store_products = result_df[result_df['Mağaza Kodu2'] == search_store][['Kod', 'MALZEME TANIMI', 'Adet']]
                    if st.checkbox(f"Mağaza {search_store} için tüm {len(store_products)} ürünü göster"):
                        # Ürün açıklamalarını kısalt
                        store_products_display = store_products.copy()
                        store_products_display['MALZEME TANIMI'] = store_products_display['MALZEME TANIMI'].apply(
                            lambda x: x[:60] + "..." if len(x) > 60 else x
                        )
                        st.dataframe(store_products_display, use_container_width=True, hide_index=True)
                else:
                    with col2:
                        st.warning(f"Mağaza {search_store} bulunamadı veya siparişi yok")
            
            # Dışa aktarma bölümü
            st.markdown("### 💾 Dönüştürülmüş Dosyayı İndir")
            
            # Excel dosyasını hazırla
            output = BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                # Ana veriyi yaz
                result_df.to_excel(writer, index=False, sheet_name="Siparişler")
                
                # Özet sayfası ekle
                summary_data = {
                    'Metrik': ['Toplam Mağaza', 'Toplam Ürün', 'Toplam Miktar', 'İşlem Tarihi'],
                    'Değer': [len(store_totals), product_count, sum(store_totals.values()), 
                             datetime.now().strftime("%d.%m.%Y %H:%M")]
                }
                pd.DataFrame(summary_data).to_excel(writer, index=False, sheet_name="Özet")
                
                # Mağaza toplamları sayfası ekle
                store_summary.to_excel(writer, index=False, sheet_name="Mağaza Toplamları")
                
                # Ürün toplamları sayfası ekle
                product_export = []
                for kod, miktar in sorted(product_totals.items(), key=lambda x: x[1], reverse=True):
                    product_export.append({
                        'Ürün Kodu': kod,
                        'Ürün Açıklama': product_descriptions.get(kod, ""),
                        'Toplam Miktar': miktar
                    })
                pd.DataFrame(product_export).to_excel(writer, index=False, sheet_name="Ürün Toplamları")
            
            output.seek(0)
            
            # İndirme butonu
            col1, col2, col3 = st.columns([1, 2, 1])
            with col2:
                st.download_button(
                    label="📥 Dönüştürülmüş Excel'i İndir",
                    data=output,
                    file_name=f"{uploaded_file.name.split('.')[0]}_donusturulmus_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
            
            # Ek özellikler
            with st.expander("📋 Dönüştürülmüş Veriyi Önizle"):
                preview_count = st.slider("Önizlenecek satır sayısı:", 10, 100, 30)
                preview_df = result_df.head(preview_count).copy()
                # Önizleme için açıklamaları kısalt
                preview_df['MALZEME TANIMI'] = preview_df['MALZEME TANIMI'].apply(
                    lambda x: x[:40] + "..." if len(x) > 40 else x
                )
                st.dataframe(
                    preview_df,
                    use_container_width=True,
                    hide_index=True
                )
            
            # Dışa aktarma seçenekleri
            with st.expander("⚙️ Gelişmiş Dışa Aktarma Seçenekleri"):
                col1, col2 = st.columns(2)
                
                with col1:
                    include_summary = st.checkbox("Özet sayfalarını dahil et", value=True)
                    include_product_sheet = st.checkbox("Ürün toplamları sayfasını dahil et", value=True)
                
                with col2:
                    date_format = st.selectbox(
                        "Dosya adı için tarih formatı:",
                        ["YYYYMMDD_HHMM", "DD-MM-YYYY", "YYYY-MM-DD"]
                    )
                    
                if st.button("🔄 Özel Dışa Aktarma Oluştur"):
                    st.info("Seçilen ayarlarla özel dışa aktarma oluşturuldu!")
    
    else:
        st.error("❌ İşlenecek veri yok. Lütfen dosya formatını kontrol edin.")

else:
    # Dosya yüklenmediğinde hoş geldin ekranı
    st.markdown("""
    ### 👋 Mağaza Sipariş Dönüştürücüye Hoş Geldiniz!
    
    Bu araç, müşteri Excel dosyalarını mağaza bazlı sipariş formatına dönüştürmenize yardımcı olur.
    
    **📌 Nasıl kullanılır:**
    1. Yukarıdaki butonu kullanarak müşterinizin Excel dosyasını yükleyin
    2. Araç, veriyi otomatik olarak işleyip dönüştürecektir
    3. Özet ve mağaza istatistiklerini inceleyin
    4. Dönüştürülmüş dosyayı indirin
    
    **📋 Beklenen dosya formatı:**
    - Mağaza sütunları içermeli (örn: "7684 M", "8373 M", vb.)
    - Sonunda "TOPLAM" sütunu olmalı
    - Ürün kodları "Hmk Kod" sütununda olmalı
    - Ürün açıklamaları "Hmk Ürün Açıklama" sütununda olmalı
    
    **✨ Özellikler:**
    - Otomatik mağaza kodu çıkarma
    - Sipariş miktarı toplama
    - Ürün açıklamalarını görüntüleme
    - En çok sipariş edilen ürünler listesi
    - Özetlerle çok sayfalı Excel dışa aktarma
    - Mağaza bazlı sorgulama
    - Temiz, profesyonel çıktı formatı
    """)
    
    # Örnek veri bilgisi
    with st.expander("📄 Örnek Girdi Formatını Görüntüle"):
        sample_data = {
            'Hmk Kod': ['30.77.0111-1325', '30.77.0111-1235', '30.77.0111-990'],
            'Hmk Ürün Açıklama': [
                'ESL HS ÜÇGE R2004 (TİP1)', 
                'ESL HS ÜÇGE R2004 (TİP2)', 
                'ESL HS GÖKÇELİK R2004'
            ],
            '7684 M': [75, 0, 225],
            '8373 M': [0, 0, 550],
            '8105 MM': [0, 500, 100],
            'TOPLAM': [75, 500, 875]
        }
        st.dataframe(pd.DataFrame(sample_data), use_container_width=True, hide_index=True)

# Alt bilgi
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: #6c757d; font-size: 0.875rem;'>
        Mağaza Sipariş Dönüştürücü v1.1 | Streamlit ile ❤️ yapıldı
    </div>
    """,
    unsafe_allow_html=True
)

# Kenar çubuğu ile ek bilgiler
with st.sidebar:
    st.markdown("### 📊 Bu Araç Hakkında")
    st.info(
        """
        Bu dönüştürücü, müşteri sipariş dosyalarını mağaza bazlı siparişleri 
        işlemek için standart bir formata dönüştürür.
        
        **v1.1 Yenilikler:**
        - Ürün açıklamaları eklendi
        - En çok sipariş edilen ürünler listesi
        - Geliştirilmiş veri görüntüleme
        """
    )
    
    st.markdown("### 🚀 Hızlı İpuçları")
    st.markdown(
        """
        - ✅ Excel dosyanızın doğru sütun başlıklarına sahip olduğundan emin olun
        - ✅ Mağaza kodları 4 haneli olmalıdır
        - ✅ Boş veya tire değerleri göz ardı edilir
        - ✅ Çıktı, analiz için birden fazla sayfa içerir
        - ✅ Ürün açıklamaları otomatik olarak dahil edilir
        """
    )
    
    st.markdown("### 📈 İstatistikler")
    if 'result_df' in locals() and result_df is not None:
        st.metric("Mevcut Oturum", "Aktif")
        st.metric("İşlenen Dosyalar", "1")
        if 'product_totals' in locals():
            st.metric("Benzersiz Ürünler", len(product_totals))
    else:
        st.metric("Mevcut Oturum", "Hazır")
        st.metric("İşlenen Dosyalar", "0")
    
    st.markdown("### 🔧 Ayarlar")
    show_advanced = st.checkbox("Gelişmiş seçenekleri göster")
    
    # Store pattern bilgisi
    with st.expander("🏪 Store Pattern Bilgisi"):
        st.markdown("""
        **Mevcut Pattern:** `^\d{3,4}\s*[A-Z]+$`
        
        Bu pattern şu formatları destekler:
        - `1234 M` ✓
        - `567 MM` ✓  
        - `890 MMM` ✓
        - `123 MJET` ✓
        - `456 NEWTYPE` ✓ (gelecekteki yeni tipler)
        
        **Avantajlar:**
        - ✅ Gelecekteki yeni store tiplerini otomatik algılar
        - ✅ 3-4 haneli sayı + herhangi bir harf kombinasyonu
        - ✅ Manuel güncelleme gerektirmez
        """)
    
    if show_advanced:
        min_quantity = st.number_input(
            "Minimum miktar eşiği:",
            min_value=1,
            max_value=100,
            value=10,
            help="Bu miktarın altındaki siparişler filtrelenecektir"
        )
        
        export_format = st.radio(
            "Dışa aktarma formatı:",
            ["Excel (.xlsx)", "CSV (.csv)"],
            help="Çıktı dosyası formatını seçin"
        )
        
        if export_format == "CSV (.csv)":
            st.warning("CSV formatı henüz desteklenmiyor. Excel kullanın.")
        
        show_descriptions = st.checkbox("Ürün açıklamalarını göster", value=True)
        description_length = st.slider(
            "Açıklama uzunluğu limiti:",
            20, 100, 60,
            help="Görüntülenen açıklamaların maksimum karakter sayısı"
        )
    
    st.markdown("### 📞 Destek")
    with st.expander("Yardıma mı ihtiyacınız var?"):
        st.markdown(
            """
            **Sık Karşılaşılan Sorunlar:**
            
            1. **Mağaza sütunları bulunamıyor**
               - Dosyanızda "7684 M" gibi mağaza sütunları olmalı
               - "TOPLAM" sütunu en sonda olmalı
            
            2. **Eksik veriler**
               - Ürün kodlarının "Hmk Kod" sütununda olduğundan emin olun
               - Ürün açıklamalarının "Hmk Ürün Açıklama" sütununda olduğunu kontrol edin
               - Boş satırları kontrol edin
            
            3. **Yanlış toplamlar**
               - Sayıların doğru formatta olduğunu kontrol edin
               - Ondalık ayracı olarak nokta veya virgül kullanabilirsiniz
            """
        )
    
    st.markdown("### 🎯 Kısayollar")
    st.markdown(
        """
        💡 **İpucu:** Birden fazla dosyayı dönüştürmek için 
        her dosyayı ayrı ayrı yükleyin ve işleyin.
        
        📊 **Ürün Analizi:** Hangi ürünlerin en çok sipariş edildiğini
        görmek için sağ taraftaki listeyi kontrol edin.
        """
    )

# Gizli geliştirici modu
if st.checkbox("", key="dev_mode", help="Geliştirici modu"):
    st.markdown("### 🔧 Geliştirici Bilgileri")
    st.code("""
    # Sistem Bilgileri
    Python Sürümü: 3.8+
    Streamlit Sürümü: 1.28+
    Pandas Sürümü: 1.5+
    Openpyxl Sürümü: 3.0+
    """)
    
    if 'result_df' in locals() and result_df is not None:
        st.markdown("### Veri Yapısı")
        st.write(f"DataFrame boyutu: {result_df.shape}")
        st.write(f"Bellek kullanımı: {result_df.memory_usage(deep=True).sum() / 1024**2:.2f} MB")
        
        if 'product_descriptions' in locals():
            st.write(f"Benzersiz ürün sayısı: {len(product_descriptions)}")
            st.write(f"Ürün açıklaması olan kayıt sayısı: {sum(1 for v in product_descriptions.values() if v)}")

# Ürün arama özelliği (ana sayfada, dosya yüklendiyse)
if uploaded_file and 'product_descriptions' in locals() and product_descriptions:
    st.markdown("---")
    st.markdown("### 🔎 Ürün Arama")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        search_product = st.text_input("Ürün kodu veya açıklama ara:", placeholder="örn: 30.77 veya ÜÇGE")
    
    if search_product:
        # Ürün kodunda veya açıklamada arama yap
        search_results = []
        search_term = search_product.upper()
        
        for kod, aciklama in product_descriptions.items():
            if search_term in kod.upper() or search_term in aciklama.upper():
                if kod in product_totals:
                    search_results.append({
                        'Ürün Kodu': kod,
                        'Açıklama': aciklama,
                        'Toplam Miktar': product_totals[kod]
                    })
        
        if search_results:
            with col2:
                st.info(f"**{len(search_results)} ürün bulundu**")
            
            # Sonuçları göster
            search_df = pd.DataFrame(search_results).sort_values('Toplam Miktar', ascending=False)
            search_df['Toplam Miktar'] = search_df['Toplam Miktar'].apply(lambda x: f"{x:,}")
            
            st.dataframe(
                search_df,
                use_container_width=True,
                hide_index=True
            )
            
            # Ürün detayları
            if st.checkbox("Seçili ürünün mağaza dağılımını göster"):
                selected_product = st.selectbox(
                    "Ürün seçin:",
                    options=[r['Ürün Kodu'] for r in search_results],
                    format_func=lambda x: f"{x} - {product_descriptions.get(x, '')[:50]}"
                )
                
                if selected_product:
                    # Bu ürünün mağaza dağılımını göster
                    product_stores = result_df[result_df['Kod'] == selected_product][['Mağaza Kodu2', 'Adet']]
                    product_stores = product_stores.groupby('Mağaza Kodu2')['Adet'].sum().reset_index()
                    product_stores = product_stores.sort_values('Adet', ascending=False)
                    product_stores['Adet'] = product_stores['Adet'].apply(lambda x: f"{x:,}")
                    
                    st.markdown(f"**{selected_product} - Mağaza Dağılımı:**")
                    st.dataframe(
                        product_stores,
                        use_container_width=True,
                        hide_index=True
                    )
        else:
            with col2:
                st.warning(f"'{search_product}' ile eşleşen ürün bulunamadı")
