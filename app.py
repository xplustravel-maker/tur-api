from flask import Flask, request, Response, render_template_string
import os
import xml.etree.ElementTree as ET
from xml.dom import minidom
import requests
import sqlite3

app = Flask(__name__)

def init_db():
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS turlar (id INTEGER PRIMARY KEY, isim TEXT, tarih TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS giderler (id INTEGER PRIMARY KEY, tur_id INTEGER, tip TEXT, fiyat REAL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS odalar (id INTEGER PRIMARY KEY, tur_id INTEGER, oda_tipi TEXT, yetiskin INTEGER, cocuk INTEGER, bebek INTEGER)''')
    conn.commit()
    conn.close()

init_db()

AGENTIS_OTEL = {
    'name': 'Cave Hotel',
    'fiyatlar': {
        'single': 570,
        'double': 590,
        'triple': 580
    },
    'child': 540,
    'baby': 0,
    'capacity': 3
}

SABIT_VARSAYILAN_BIRIM = 'TRY'

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
        return {'EUR_TRY': 48.72, 'USD_TRY': 41.98, 'EUR_USD': 1.16, 'USD_EUR': 0.86}

KUR = get_exchange_rates()

def convert_currency(miktar, from_birim, to_birim):
    if from_birim == to_birim:
        return miktar
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

def hesapla_oda_breakdown(odalar_list, sabit_giderler, hedef_para_birimi='TRY'):
    # Sabit toplam
    sabit_toplam_try = sum(gider['fiyat'] for gider in sabit_giderler)
    sabit_toplam_hedef = convert_currency(sabit_toplam_try, SABIT_VARSAYILAN_BIRIM, hedef_para_birimi)
   
    # Toplam kişi hesapla
    toplam_kisi = sum(oda['yetiskin'] + oda['cocuk'] + oda['bebek'] for oda in odalar_list)
    if toplam_kisi == 0:
        return {'hata': 'Kişi sayısı 0 olamaz'}
   
    sabit_kisi_basi = sabit_toplam_hedef / toplam_kisi
   
    oda_breakdowns = []
    genel_toplam = 0
    for oda in odalar_list:
        oda_kisi = oda['yetiskin'] + oda['cocuk'] + oda['bebek']
        oda_sabit_ek = oda_kisi * sabit_kisi_basi
       
        pp_fiyat = AGENTIS_OTEL['fiyatlar'].get(oda['oda_tipi'], AGENTIS_OTEL['fiyatlar']['double'])
        otel_yetiskin = oda['yetiskin'] * pp_fiyat
        otel_cocuk = oda['cocuk'] * AGENTIS_OTEL['child']
        otel_bebek = oda['bebek'] * AGENTIS_OTEL['baby']
        otel_toplam_eur = otel_yetiskin + otel_cocuk + otel_bebek
        otel_toplam_hedef = convert_currency(otel_toplam_eur, 'EUR', hedef_para_birimi)
       
        oda_toplam = round(otel_toplam_hedef + oda_sabit_ek, 2)
        genel_toplam += oda_toplam
       
        oda_breakdowns.append({
            'oda_num': len(oda_breakdowns) + 1,
            'oda_tipi': oda['oda_tipi'],
            'kişi_dağılım': f"{oda['yetiskin']}Y + {oda['cocuk']}Ç + {oda['bebek']}B",
            'otel_fiyat': round(otel_toplam_hedef, 2),
            'sabit_ek': round(oda_sabit_ek, 2),
            'toplam': oda_toplam
        })
   
    return {
        'oda_breakdowns': oda_breakdowns,
        'genel_toplam': genel_toplam,
        'para_birimi': hedef_para_birimi,
        'toplam_kisi': toplam_kisi,
        'sabit_kisi_basi': round(sabit_kisi_basi, 2)
    }

def create_xml(breakdown, tur_adi='Kapadokya Turu'):
    root = ET.Element('tours')
    tour = ET.SubElement(root, 'tour')
    tour.set('id', '1')
    ET.SubElement(tour, 'name').text = tur_adi
    ET.SubElement(tour, 'total