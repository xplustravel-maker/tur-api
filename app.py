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
    sabit_toplam_try = sum(gider['fiyat'] for gider in sabit_giderler)
    sabit_toplam_hedef = convert_currency(sabit_toplam_try, SABIT_VARSAYILAN_BIRIM, hedef_para_birimi)
   
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
    ET.SubElement(tour, 'total_price').text = str(breakdown['genel_toplam'])
    ET.SubElement(tour, 'currency').text = breakdown['para_birimi']
    ET.SubElement(tour, 'total_persons').text = str(breakdown['toplam_kisi'])
   
    persons = ET.SubElement(tour, 'persons')
    persons.text = f"Toplam {breakdown['toplam_kisi']} kişi (oda bazlı)"
   
    breakdown_el = ET.SubElement(tour, 'breakdown')
    for oda in breakdown['oda_breakdowns']:
        oda_el = ET.SubElement(breakdown_el, 'oda')
        oda_el.set('num', str(oda['oda_num']))
        oda_el.set('tip', oda['oda_tipi'])
        ET.SubElement(oda_el, 'kisi_dagilim').text = oda['kişi_dağılım']
        ET.SubElement(oda_el, 'otel_fiyat').text = str(oda['otel_fiyat'])
        ET.SubElement(oda_el, 'sabit_ek').text = str(oda['sabit_ek'])
        ET.SubElement(oda_el, 'toplam').text = str(oda['toplam'])
   
    ET.SubElement(breakdown_el, 'sabit_kisi_basi').text = str(breakdown['sabit_kisi_basi'])
   
    kur_el = ET.SubElement(tour, 'exchange_rates')
    for k, v in KUR.items():
        ET.SubElement(kur_el, 'rate', pair=k).text = str(v)
   
    rough_string = ET.tostring(root, 'unicode')
    reparsed = minidom.parseString(rough_string)
    return reparsed.toprettyxml(indent="  ")

@app.route('/calculate-oda-fiyatlari', methods=['POST'])
def calculate_oda_fiyatlari():
    global KUR
    KUR = get_exchange_rates()
   
    data = request.json
    tur_id = data.get('tur_id')
    odalar_list = data.get('odalar', [])
    hedef_para_birimi = data.get('hedef_para_birimi', 'TRY')
    tur_adi = data.get('tur_adi', 'Vito Kapadokya Turu')
   
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT tip, fiyat FROM giderler WHERE tur_id = ?", (tur_id,))
    db_giderler = [{'tip': row[0], 'fiyat': row[1]} for row in c.fetchall()]
    conn.close()
   
    sabit_giderler = db_giderler or [{'tip': 'arac', 'fiyat': 5000}, {'tip': 'yat', 'fiyat': 2000}]
   
    if not odalar_list:
        return {'hata': 'Oda listesi zorunlu'}
   
    breakdown = hesapla_oda_breakdown(odalar_list, sabit_giderler, hedef_para_birimi)
    xml_output = create_xml(breakdown, tur_adi)
   
    return Response(xml_output, mimetype='application/xml')

# Alias route for old endpoint
@app.route('/hesapla-paket-xml', methods=['POST'])
def hesapla_paket_xml():
    return calculate_oda_fiyatlari()

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
        <h1>Tur Yönetimi (Oda Bazlı Sabit Bölüşüm)</h1>
        <h2>1. Tur Seç ve Sabit Gider Ekle</h2>
        <select id="turSelect">
            <option value="">Yeni Tur Ekle</option>
            {% for tur in turlar %}
            <option value="{{ tur[0] }}"> {{ tur[1] }} - {{ tur[2] }}</option>
            {% endfor %}
        </select>
        <button onclick="addTur()">Yeni Tur Ekle</button>
        <div id="giderForm">
            <input type="text" id="giderTip" placeholder="Tip (arac, rehber, yat, transfer)">
            <input type="number" id="giderFiyat" placeholder="Fiyat (TL, toplam)">
            <button onclick="addGider()">Ekle (Tur'a Bağla)</button>
        </div>
        <ul id="giderList"></ul>
       
        <h2>2. Satış Simülasyonu (Oda Dağılımı Gir)</h2>
        <div id="odaForm">
            <button onclick="addOda()">Yeni Oda Ekle</button>
            <div id="odalar"></div>
        </div>
        <button onclick="hesaplaOda()">Hesapla Oda Fiyatları</button>
        <div id="sonuc"></div>
       
        <script>
            let giderler = [];
            let odalar = [];
            let turId = null;
           
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
                if (tip && fiyat && turId) {
                    fetch('/add-gider', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({tip: tip, fiyat: fiyat, tur_id: turId})
                    }).then(r => r.json()).then(data => {
                        giderler.push({tip: tip, fiyat: fiyat});
                        document.getElementById('giderList').innerHTML += `<li>${tip}: ${fiyat} TL (Toplam)</li>`;
                        document.getElementById('giderTip').value = '';
                        document.getElementById('giderFiyat').value = '';
                    });
                } else {
                    alert('Tur seç ve fiyat gir!');
                }
            }
           
            document.getElementById('turSelect').addEventListener('change', function() {
                turId = this.value;
                if (turId) {
                    fetch(`/load-giderler/${turId}`).then(r => r.json()).then(data => {
                        giderler = data.giderler;
                        let list = '';
                        giderler.forEach(g => list += `<li>${g.tip}: ${g.fiyat} TL</li>`);
                        document.getElementById('giderList').innerHTML = list;
                    });
                }
            });
           
            function addOda() {
                const odaNum = odalar.length + 1;
                const odaHtml = `
                    <div id="oda${odaNum}">
                        Oda ${odaNum}: <select id="odaTipi${odaNum}">
                            <option value="double">Double</option>
                            <option value="single">Single</option>
                            <option value="triple">Triple</option>
                        </select>
                        Yetişkin: <input type="number" id="yetiskin${odaNum}" value="2">
                        Çocuk: <input type="number" id="cocuk${odaNum}" value="0">
                        Bebek: <input type="number" id="bebek${odaNum}" value="0">
                        <button onclick="removeOda(${odaNum})">Sil</button>
                    </div>
                `;
                document.getElementById('odalar').innerHTML += odaHtml;
                odalar.push(odaNum);
            }
           
            function removeOda(num) {
                document.getElementById('oda' + num).remove();
                odalar = odalar.filter(n => n != num);
            }
           
            function hesaplaOda() {
                if (!turId || odalar.length == 0) {
                    alert('Tur seç ve en az 1 oda ekle!');
                    return;
                }
                const odalar_list = [];
                odalar.forEach(num => {
                    odalar_list.push({
                        oda_tipi: document.getElementById('odaTipi' + num).value,
                        yetiskin: parseInt(document.getElementById('yetiskin' + num).value),
                        cocuk: parseInt(document.getElementById('cocuk' + num).value),
                        bebek: parseInt(document.getElementById('bebek' + num).value)
                    });
                });
                const data = {
                    tur_id: turId,
                    odalar: odalar_list,
                    hedef_para_birimi: 'TRY'
                };
                fetch('/calculate-oda-fiyatlari', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify(data)
                }).then(r => r.text()).then(xml => {
                    document.getElementById('sonuc').innerHTML = `<pre>${xml}</pre><button onclick="satisHazir()">Satışa Hazırla</button>`;
                });
            }
           
            function satisHazir() {
                alert('Oda fiyatları Agentis\'e entegre edildi – satış hazır!');
            }
        </script>
    </body>
    </html>
    """
    return render_template_string(html_template, turlar=turlar)

@app.route('/load-giderler/<int:tur_id>', methods=['GET'])
def load_giderler(tur_id):
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    c.execute("SELECT tip, fiyat FROM giderler WHERE tur_id = ?", (tur_id,))
    giderler = [{'tip': row[0], 'fiyat': row[1]} for row in c.fetchall()]
    conn.close()
    return {'giderler': giderler}

@app.route('/add-gider', methods=['POST'])
def add_gider():
    data = request.json
    tip = data.get('tip')
    fiyat = data.get('fiyat', 0)
    tur_id = data.get('tur_id')
    if tip and fiyat and tur_id:
        conn = sqlite3.connect('tur_db.sqlite')
        c = conn.cursor()
        c.execute("INSERT INTO giderler (tur_id, tip, fiyat) VALUES (?, ?, ?)", (tur_id, tip, fiyat))
        conn.commit()
        conn.close()
        print(f"Yeni gider eklendi: {tip} - {fiyat} TL (Tur ID: {tur_id})")
        return {'status': 'eklendi', 'tip': tip, 'fiyat': fiyat}
    return {'status': 'hata', 'mesaj': 'Tip, fiyat ve tur_id zorunlu'}

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

@app.route('/fetch-agentis-turs', methods=['GET'])
def fetch_agentis_turs():
    simule_turlar = [
        {'id': 1, 'isim': 'Kapadokya Turu 2 Gün', 'tarih': '01/11/2025'},
        {'id': 2, 'isim': 'İstanbul Turu Vito', 'tarih': '15/11/2025'},
        {'id': 3, 'isim': 'Sprinter Antalya', 'tarih': '20/11/2025'}
    ]
    return {'turlar': simule_turlar, 'mesaj': 'Agentis simüle – gerçek API için güncelle'}

@app.route('/integrate-tur', methods=['POST'])
def integrate_tur():
    data = request.json
    tur_id = data.get('tur_id')
    odalar_list = data.get('odalar', [])
    sabit_giderler = data.get('sabit_giderler', [])
    hedef_para_birimi = data.get('hedef_para_birimi', 'TRY')
   
    conn = sqlite3.connect('tur_db.sqlite')
    c = conn.cursor()
    for oda in odalar_list:
        c.execute("INSERT INTO odalar (tur_id, oda_tipi, yetiskin, cocuk, bebek) VALUES (?, ?, ?, ?, ?)", 
                  (tur_id, oda['oda_tipi'], oda['yetiskin'], oda['cocuk'], oda['bebek']))
    for gider in sabit_giderler:
        c.execute("INSERT INTO giderler (tur_id, tip, fiyat) VALUES (?, ?, ?)", (tur_id, gider['tip'], gider['fiyat']))
    conn.commit()
    conn.close()
   
    breakdown = hesapla_oda_breakdown(odalar_list, sabit_giderler, hedef_para_birimi)
    xml_output = create_xml(breakdown, 'Entegre Tur')
   
    return Response(xml_output, mimetype='application/xml')

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)