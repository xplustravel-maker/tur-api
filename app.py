from flask import Flask, request, Response
import xml.etree.ElementTree as ET
from xml.dom import minidom
import requests  # Kur için

app = Flask(__name__)

# Agentis otel verisi (EUR bazlı, panelden güncelle)
AGENTIS_OTEL = {
    'name': 'Cave Hotel',
    'fiyatlar': {
        'single': 570,
        'double': 590,
        'triple': 580
    },
    'child': 540,
    'baby': 0,  # Ücretsiz
    'capacity': 3
}

SABIT_VARSAYILAN_BIRIM = 'TRY'

# Kur çekme (gerçek API, fallback 23.10.2025 kur: EUR=48.72 TRY, USD=41.98 TRY)
def get_exchange_rates(base='USD'):
    try:
        url = f"https://api.exchangerate-api.com/v4/latest/{base}"
        response = requests.get(url, timeout=5)
        data = response.json()
        rates = data['rates']
        eur_try = rates['TRY'] / rates['EUR']
        usd_try = rates['TRY']
        eur_usd = 1 / rates['EUR']
        return {
            'EUR_TRY': round(eur_try, 4),
            'USD_TRY': round(usd_try, 4),
            'EUR_USD': round(eur_usd, 4),
            'USD_EUR': round(rates['EUR'], 4)
        }
    except Exception:
        return {
            'EUR_TRY': 48.72,
            'USD_TRY': 41.98,
            'EUR_USD': 1.16,
            'USD_EUR': 0.86
        }

KUR = get_exchange_rates()  # Başlangıçta çek

def convert_currency(miktar, from_birim, to_birim):
    if from_birim == to_birim:
        return miktar
    # TRY ara birim
    if from_birim == 'TRY':
        if to_birim == 'EUR':
            return miktar / KUR['EUR_TRY']
        elif to_birim == 'USD':
            return miktar / KUR['USD_TRY']
    elif from_birim == 'EUR':
        if to_birim == 'TRY':
            return miktar * KUR['EUR_TRY']
        elif to_birim == 'USD':
            return miktar * KUR['EUR_USD']
    elif from_birim == 'USD':
        if to_birim == 'TRY':
            return miktar * KUR['USD_TRY']
        elif to_birim == 'EUR':
            return miktar / KUR['EUR_USD']
    return miktar

def hesapla_breakdown(yetiskin, cocuk, bebek, oda_tipi='double', sabit_giderler=[], ek_oda_sayisi=0, hedef_para_birimi='TRY'):
    otel = AGENTIS_OTEL
    pp_fiyat = otel['fiyatlar'].get(oda_tipi, otel['fiyatlar']['double'])  # EUR
    
    toplam_kisi = yetiskin + cocuk + bebek
    otomatik_oda_sayisi = -(-toplam_kisi // otel['capacity'])
    toplam_oda_sayisi = otomatik_oda_sayisi + ek_oda_sayisi
    
    # Otel EUR'da
    otel_yetiskin = yetiskin * pp_fiyat
    otel_cocuk = cocuk * otel['child']
    otel_bebek = bebek * otel['baby']  # 0
    otel_ek_oda = ek_oda_sayisi * pp_fiyat
    otel_toplam_eur = otel_yetiskin + otel_cocuk + otel_bebek + otel_ek_oda
    otel_toplam_hedef = convert_currency(otel_toplam_eur, 'EUR', hedef_para_birimi)
    
    # Sabit TRY'de topla, dönüştür
    sabit_toplam_try = sum(gider['fiyat'] for gider in sabit_giderler)
    sabit_toplam_hedef = convert_currency(sabit_toplam_try, SABIT_VARSAYILAN_BIRIM, hedef_para_birimi)
    
    sabit_kisi_basi_hedef = sabit_toplam_hedef / toplam_kisi if toplam_kisi > 0 else 0
    
    # Sabit breakdown
    sabit_breakdown = {}
    for gider in sabit_giderler:
        kisi_basi_try = gider['fiyat'] / toplam_kisi if toplam_kisi > 0 else 0
        kisi_basi_hedef = convert_currency(kisi_basi_try, SABIT_VARSAYILAN_BIRIM, hedef_para_birimi)
        sabit_breakdown[gider['tip']] = {'toplam': convert_currency(gider['fiyat'], SABIT_VARSAYILAN_BIRIM, hedef_para_birimi), 'kisi_basi': round(kisi_basi_hedef, 2)}
    
    genel_toplam_hedef = round(otel_toplam_hedef + sabit_toplam_hedef, 2)
    
    return {
        'toplam_oda_sayisi': toplam_oda_sayisi,
        'otomatik_oda_sayisi': otomatik_oda_sayisi,
        'ek_oda_sayisi': ek_oda_sayisi,
        'otel_toplam': round(otel_toplam_hedef, 2),
        'sabitler': sabit_breakdown,
        'sabit_toplam': round(sabit_toplam_hedef, 2),
        'sabit_kisi_basi': round(sabit_kisi_basi_hedef, 2),
        'genel_toplam': genel_toplam_hedef,
        'toplam_kisi': toplam_kisi,
        'para_birimi': hedef_para_birimi,
        'kur_bilgisi': KUR
    }

def create_xml(breakdown, tur_adi='Kapadokya Turu'):
    root = ET.Element('tours')
    tour = ET.SubElement(root, 'tour')
    tour.set('id', '1')
    ET.SubElement(tour, 'name').text = tur_adi
    ET.SubElement(tour, 'total_price').text = str(breakdown['genel_toplam'])
    ET.SubElement(tour, 'currency').text = breakdown['para_birimi']
    ET.SubElement(tour, 'total_persons').text = str(breakdown['toplam_kisi'])
    
    persons = ET.SubElement(tour, 'persons')
    persons.text = f"{breakdown.get('yetiskin',3)} yetiskin + {breakdown.get('cocuk',1)} cocuk + {breakdown.get('bebek',0)} bebek (ücretsiz)"
    
    breakdown_el = ET.SubElement(tour, 'breakdown')
    ET.SubElement(breakdown_el, 'component', type='otel').text = f"{breakdown['otel_toplam']} {breakdown['para_birimi']} ({breakdown['toplam_oda_sayisi']} oda, {breakdown['ek_oda_sayisi']} ek)"
    
    for tip, detay in breakdown['sabitler'].items():
        ET.SubElement(breakdown_el, 'component', type=tip).text = f"{detay['toplam']} {breakdown['para_birimi']} (kişi başı {detay['kisi_basi']} {breakdown['para_birimi']})"
    
    kur_el = ET.SubElement(tour, 'exchange_rates')
    for k, v in breakdown['kur_bilgisi'].items():
        ET.SubElement(kur_el, 'rate', pair=k).text = str(v)
    
    rough_string = ET.tostring(root, 'unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

@app.route('/hesapla-paket-xml', methods=['POST'])
def hesapla_xml():
    global KUR
    KUR = get_exchange_rates()  # Güncel kur
    
    data = request.json
    yetiskin = data.get('yetiskin', 3)
    cocuk = data.get('cocuk', 1)
    bebek = data.get('bebek', 0)
    oda_tipi = data.get('oda_tipi', 'double')
    sabit_giderler = data.get('sabit_giderler', [{'tip': 'arac', 'fiyat': 5000}, {'tip': 'yat', 'fiyat': 2000}])
    ek_oda_sayisi = data.get('ek_oda_sayisi', 0)
    hedef_para_birimi = data.get('hedef_para_birimi', 'TRY')
    tur_adi = data.get('tur_adi', 'Vito Kapadokya Turu')
    
    breakdown = hesapla_breakdown(yetiskin, cocuk, bebek, oda_tipi, sabit_giderler, ek_oda_sayisi, hedef_para_birimi)
    breakdown['yetiskin'] = yetiskin
    breakdown['cocuk'] = cocuk
    breakdown['bebek'] = bebek
    
    xml_output = create_xml(breakdown, tur_adi)
    
    return Response(xml_output, mimetype='application/xml')

if __name__ == '__main__':
    import os
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)