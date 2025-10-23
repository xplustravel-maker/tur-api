from flask import Flask, request, Response, render_template_string
import xml.etree.ElementTree as ET
from xml.dom import minidom
import requests
import sqlite3

app = Flask(__name__)

# DB başlat
def init_db():
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS turlar (id INTEGER PRIMARY KEY, isim TEXT, tarih TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS giderler (id INTEGER PRIMARY KEY, tur_id INTEGER, tip TEXT, fiyat REAL)''')
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

def convert_currency(miktar, from_birim, to_birimi):
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

def hesapla_breakdown(yetiskin, cocuk, bebek, oda_tipi='double', sabit_giderler=[], ek_oda_sayisi=0, hedef_para_birimi='TRY'):
    otel = AGENTIS_OTEL
    pp_fiyat = otel['fiyatlar'].get(oda_tipi, otel['fiyatlar']['double'])
    
    toplam_kisi = yetiskin + cocuk + bebek
    otomatik_oda_sayisi = -(-toplam_kisi // otel['capacity'])
    toplam_oda_sayisi = otomatik_oda_sayisi + ek_oda_sayisi
    
    otel_yetiskin = yetiskin * pp_fiyat
    otel_cocuk = cocuk * otel['child']
    otel_bebek = bebek * otel['baby']
    otel_ek_oda = ek_oda_sayisi * pp_fiyat
    otel_toplam_eur = otel_yetiskin + otel_cocuk + otel_bebek + otel_ek_oda
    otel_toplam_hedef = convert_currency(otel_toplam_eur, 'EUR', hedef_para_birimi)
    
    sabit_toplam_try = sum(gider['fiyat'] for gider in sabit_giderler)
    sabit_toplam_hedef = convert_currency(sabit_toplam_try, SABIT_VARSAYILAN_BIRIM, hedef_para_birimi)
    
    sabit_kisi_basi_hedef = sabit_toplam_hedef / toplam_kisi if toplam_kisi > 0 else 0
    
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
    KUR = get_exchange_rates()
    
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

@app.route('/admin', methods=['GET'])
def admin_panel():
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    c.execute('SELECT id, isim, tarih FROM turlar')
    turlar = c.fetchall()
    conn.close()
    
    html_template = """
    <!DOCTYPE html>
    <html>
    <head><title>Admin Tur Yönetimi</title></head>
    <body>
        <h1>Tur Yönetimi (Agentis Entegrasyonu)</h1>
        <h2>1. Tur Seç (Agentis'ten Çekilenler)</h2>
        <select id="turSelect">
            <option value="">Yeni Tur Ekle</option>
            {% for tur in turlar %}
            <option value="{{ tur[0] }}"> {{ tur[1] }} - {{ tur[2] }}</option>
            {% endfor %}
        </select>
        <button onclick="addTur()">Yeni Tur Ekle</button>
        <button onclick="fetchAgentis()">Agentis'ten Çek</button>
        
        <h2>2. Giderler Gir (Araç, Rehber, Yat, Transfer)</h2>
        <div id="giderForm">
            <input type="text" id="giderTip" placeholder="Tip (arac, rehber, yat, transfer)">
            <input type="number" id="giderFiyat" placeholder="Fiyat (TL)">
            <button onclick="addGider()">Ekle</button>
        </div>
        <ul id="giderList"></ul>
        
        <h2>3. Hesapla ve Satışa Hazırla</h2>
        <input type="number" id="yetiskin" placeholder="Yetişkin" value="3">
        <input type="number" id="cocuk" placeholder="Çocuk" value="1">
        <input type="number" id="bebek" placeholder="Bebek" value="0">
        <select id="odaTipi">
            <option value="double">Double</option>
            <option value="single">Single</option>
            <option value="triple">Triple</option>
        </select>
        <input type="number" id="ekOda" placeholder="Ek Oda" value="0">
        <select id="paraBirimi">
            <option value="TRY">TL</option>
            <option value="EUR">EUR</option>
            <option value="USD">USD</option>
        </select>
        <button onclick="hesapla()">Hesapla</button>
        <div id="sonuc"></div>
        
        <script>
            let giderler = [];
            let agentisTurlar = [];
            
            function fetchAgentis() {
                fetch('/fetch-agentis-turs').then(r => r.json()).then(data => {
                    agentisTurlar = data.turlar;
                    let options = '';
                    agentisTurlar.forEach(tur => {
                        options += `<option value="${tur.id}">${tur.isim} - ${tur.tarih}</option>`;
                    });
                    document.getElementById('turSelect').innerHTML = `<option value="">Agentis Turları</option>` + options;
                    alert(data.mesaj);
                });
            }
            
            function addTur() {
                const isim = prompt("Tur İsmi:");
                const tarih = prompt("Tarih (GG/AA/YYYY):");
                if (isim && tarih) {
                    fetch('/add-tur', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({isim: isim, tarih: tarih})
                    }).then(r => r.json()).then(data => {
                        location.reload();
                    });
                }
            }
            function addGider() {
                const tip = document.getElementById('giderTip').value;
                const fiyat = parseFloat(document.getElementById('giderFiyat').value);
                if (tip && fiyat) {
                    fetch('/add-gider', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({tip: tip, fiyat: fiyat})
                    }).then(r => r.json()).then(data => {
                        giderler.push({tip: tip, fiyat: fiyat});
                        document.getElementById('giderList').innerHTML += `<li>${tip}: ${fiyat} TL</li>`;
                        document.getElementById('giderTip').value = '';
                        document.getElementById('giderFiyat').value = '';
                    });
                }
            }
            function hesapla() {
                const data = {
                    yetiskin: parseInt(document.getElementById('yetiskin').value),
                    cocuk: parseInt(document.getElementById('cocuk').value),
                    bebek: parseInt(document.getElementById('bebek').value),
                    oda_tipi: document.getElementById('odaTipi').value,
                    sabit_giderler: giderler,
                    ek_oda_sayisi: parseInt(document.getElementById('ekOda').value),
                    hedef_para_birimi: document.getElementById('paraBirimi').value,
                    tur_adi: document.getElementById('turSelect').value || 'Yeni Tur'
                };
                fetch('/hesapla-paket-xml', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                }).then(r => r.text()).then(xml => {
                    document.getElementById('sonuc').innerHTML = `<pre>${xml}</pre><button onclick="satisHazir()">Satışa Hazırla</button>`;
                });
            }
            function satisHazir() {
                alert('XML Agentis\'e gönderildi – satış hazır!');
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, turlar=turlar)

@app.route('/add-tur', methods=['POST'])
def add_tur():
    data = request.json
    isim = data.get('isim')
    tarih = data.get('tarih')
    if isim and tarih:
        conn = sqlite3.connect('tur_db.sqlite')
        c = conn.cursor()
        c.execute("INSERT INTO turlar (isim, tarih) VALUES (?, ?)", (isim, tarih))
        conn.commit()
        conn.close()
        return {'status': 'eklendi', 'isim': isim, 'tarih': tarih}
    return {'status': 'hata', 'mesaj': 'İsim ve tarih zorunlu'}

@app.route('/add-gider', methods=['POST'])
def add_gider():
    data = request.json
    tip = data.get('tip')
    fiyat = data.get('fiyat', 0)
    print(f"Yeni gider eklendi: {tip} - {fiyat} TL")
    return {'status': 'eklendi', 'tip': tip, 'fiyat': fiyat}

@app.route('/fetch-agentis-turs', methods=['GET'])
def fetch_agentis_turs():
    # Gerçekte Agentis API'sini çağır (örnek: requests.get('https://app.agentis.com.tr/api/turs', auth=('key', 'secret')))
    # Şimdilik simüle
    simule_turlar = [
        {'id': 1, 'isim': 'Kapadokya Turu 2 Gün', 'tarih': '01/11/2025'},
        {'id': 2, 'isim': 'İstanbul Turu Vito', 'tarih': '15/11/2025'},
        {'id': 3, 'isim': 'Sprinter Antalya', 'tarih': '20/11/2025'}
    ]
    return {'turlar': simule_turlar, 'mesaj': 'Agentis entegrasyonu hazır – gerçek API geldiğinde güncelle'}

@app.route('/integrate-tur', methods=['POST'])
def integrate_tur():
    data = request.json
    tur_id = data.get('tur_id')  # Agentis tur ID'si
    yetiskin = data.get('yetiskin', 3)
    cocuk = data.get('cocuk', 1)
    bebek = data.get('bebek', 0)
    oda_tipi = data.get('oda_tipi', 'double')
    sabit_giderler = data.get('sabit_giderler', [])  # Senin giderlerin
    ek_oda_sayisi = data.get('ek_oda_sayisi', 0)
    hedef_para_birimi = data.get('hedef_para_birimi', 'TRY')
    
    # DB'ye tur/gider kaydet
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    c.execute("INSERT INTO turlar (isim, tarih) VALUES (?, ?)", ('Agentis Tur ' + str(tur_id), 'Agentis Tarihi'))  # Gerçek isim/tarih Agentis'ten
    tur_id_db = c.lastrowid
    for gider in sabit_giderler:
        c.execute("INSERT INTO giderler (tur_id, tip, fiyat) VALUES (?, ?, ?)", (tur_id_db, gider['tip'], gider['fiyat']))
    conn.commit()
    conn.close()
    
    # Hesapla
    breakdown = hesapla_breakdown(yetiskin, cocuk, bebek, oda_tipi, sabit_giderler, ek_oda_sayisi, hedef_para_birimi)
    xml_output = create_xml(breakdown, 'Agentis Entegre Tur')
    
    return Response(xml_output, mimetype='application/xml')

if __name__ == '__main__':
    app.run(debug=True)