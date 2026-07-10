from flask import (Flask, render_template, request, redirect, url_for,
                   session, jsonify, send_file, send_from_directory)
import pymysql, pymysql.cursors, hashlib, random, os, io
from datetime import date, datetime
from functools import wraps

app = Flask(__name__)
app.secret_key = "dematiq-2026-secret-key"

@app.after_request
def add_header(r):
    r.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    r.headers["Pragma"] = "no-cache"
    r.headers["Expires"] = "0"
    r.headers['Cache-Control'] = 'public, max-age=0'
    return r

@app.route("/favicon.ico")
def favicon():
    return send_from_directory(os.path.join(app.root_path, "static"),
                               "favicon.ico", mimetype="image/x-icon")

DB = dict(host="localhost", user="root", password="root",
          database="cotizaciones_dematiq", charset="utf8mb4",
          cursorclass=pymysql.cursors.DictCursor, autocommit=True)

def get_db():
    return pymysql.connect(**DB)

def q(sql, params=(), fetch="all"):
    conn = get_db()
    with conn.cursor() as c:
        c.execute(sql, params)
        if fetch == "all":
            result = c.fetchall()
        elif fetch == "one":
            result = c.fetchone()
        else:
            result = c.lastrowid
    conn.close()
    return result

def ex(sql, params=()):
    conn = get_db()
    with conn.cursor() as c:
        c.execute(sql, params)
        lid = c.lastrowid
    conn.close()
    return lid

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()

def verify_pw(plain, stored):
    import re
    if re.match(r"^\$2[aby]\$", stored):
        try:
            import bcrypt
            return bcrypt.checkpw(plain.encode(), stored.encode())
        except Exception:
            pass
    return hash_pw(plain) == stored

@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard") if "user_id" in session else url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form.get("email", "").strip()
        pwd   = request.form.get("password", "")
        user  = q("SELECT * FROM usuarios WHERE email=%s", (email,), fetch="one")
        if not user or not verify_pw(pwd, user["password_hash"]):
            error = "Correo o contraseña incorrectos."
        else:
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            session["user_nombre"] = user.get("nombre") or user["email"]
            return redirect(url_for("dashboard"))
    return render_template("login.html", error=error)

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/registro", methods=["GET", "POST"])
def registro():
    error = None
    success = None
    if request.method == "POST":
        nombre = request.form.get("nombre", "").strip()
        email  = request.form.get("email", "").strip()
        pwd    = request.form.get("password", "")
        pwd2   = request.form.get("password2", "")
        if not nombre or not email or not pwd:
            error = "Todos los campos son obligatorios."
        elif pwd != pwd2:
            error = "Las contraseñas no coinciden."
        elif len(pwd) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        else:
            existe = q("SELECT id FROM usuarios WHERE email=%s", (email,), fetch="one")
            if existe:
                error = "Ya existe una cuenta con ese correo."
            else:
                try:
                    ex("INSERT INTO usuarios (nombre, email, password_hash) VALUES (%s,%s,%s)",
                       (nombre, email, hash_pw(pwd)))
                    success = "Cuenta creada correctamente. Ya puedes iniciar sesión."
                except Exception as e:
                    error = f"Error al crear cuenta: {e}"
    return render_template("registro.html", error=error, success=success)

@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html",
                           user_email=session.get("user_email"),
                           user_nombre=session.get("user_nombre"))

@app.route("/proyecto/<int:pid>")
@login_required
def proyecto(pid):
    p = q("SELECT * FROM proyectos WHERE id=%s", (pid,), fetch="one")
    if not p:
        return redirect(url_for("dashboard"))
    return render_template("proyecto.html", proyecto=p,
                           user_email=session.get("user_email"))

@app.route("/api/stats")
@login_required
def api_stats():
    stats = q("""SELECT COUNT(*) total,
               SUM(CASE WHEN MONTH(fecha_creacion)=MONTH(CURDATE())
                         AND YEAR(fecha_creacion)=YEAR(CURDATE()) THEN 1 ELSE 0 END) mes,
               COALESCE(SUM(total_mn),0) monto
               FROM proyectos""", fetch="one")
    chart = q("""SELECT numero_proyecto, nombre_proyecto, total_mn, total_usd
                 FROM proyectos ORDER BY created_at DESC LIMIT 8""")
    return jsonify(stats=stats, chart=list(chart))

@app.route("/api/proyectos")
@login_required
def api_proyectos():
    search = request.args.get("q", "")
    if search:
        rows = q("""SELECT * FROM proyectos WHERE nombre_proyecto LIKE %s
                    OR empresa_cliente LIKE %s OR numero_proyecto LIKE %s
                    ORDER BY created_at DESC""",
                 (f"%{search}%", f"%{search}%", f"%{search}%"))
    else:
        rows = q("SELECT * FROM proyectos ORDER BY created_at DESC")
    return jsonify(data=list(rows))

@app.route("/api/proyectos/create", methods=["POST"])
@login_required
def api_crear_proyecto():
    d = request.json or {}
    nombre = (d.get("nombre_proyecto") or "").strip()
    if not nombre:
        return jsonify(error="Nombre requerido"), 400
    num = f"DM-{date.today().year}-{random.randint(1000,9999)}"
    pid = ex("""INSERT INTO proyectos
               (numero_proyecto,nombre_proyecto,empresa_cliente,contacto_cliente,
                telefono_cliente,email_cliente,atencion,referencia,carpeta_link,
                fecha_creacion,usuario_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
             (num, nombre, d.get("empresa_cliente",""), d.get("contacto_cliente",""),
              d.get("telefono_cliente",""), d.get("email_cliente",""),
              d.get("atencion",""), d.get("referencia",""), d.get("carpeta_link",""),
              date.today().isoformat(), session["user_id"]))

    secciones = [
        ("PRESE","PRESENTACIÓN","mano_obra",1,"#64748b"),
        ("REPORTE","REPORTE GENERAL","mano_obra",2,"#16a34a"),
        ("ING_MO","ING. MANO DE OBRA","mano_obra",3,"#2563eb"),
        ("E_CONTROL","EQUIPO DE CONTROL","equipo",4,"#0d47a1"),
        ("E_ELECTRICO","EQUIPO ELÉCTRICO","equipo",5,"#0284c7"),
        ("E_NEUMATICO","EQUIPO NEUMÁTICO","equipo",6,"#0891b2"),
        ("E_MECANICO","EQUIPO MECÁNICO","equipo",7,"#ea580c"),
        ("INSUMOS","INSUMOS","equipo",8,"#dc2626"),
        ("LISTAS","LISTAS","equipo",9,"#7c3aed"),
        ("IO","I/O","equipo",10,"#475569"),
        ("CONDICIONES","CONDICIONES COMERCIALES","mano_obra",11,"#475569"),
    ]
    for code,title,tipo,orden,color in secciones:
        ex("INSERT INTO secciones (proyecto_id,codigo,titulo,tipo,orden,color) VALUES (%s,%s,%s,%s,%s,%s)",
           (pid,code,title,tipo,orden,color))

    conds = [
        ("C1","Precios expresados en Moneda Nacional con IVA incluido.",1),
        ("C2","Tiempo de entrega según especificaciones del proyecto.",2),
        ("C3","Anticipo del 50% para iniciar trabajos.",3),
        ("C4","Garantía de 12 meses en equipos instalados.",4),
        ("C5","Cotización válida por 30 días naturales.",5),
    ]
    for code,cont,orden in conds:
        ex("INSERT INTO condiciones_comerciales (proyecto_id,codigo,contenido,orden) VALUES (%s,%s,%s,%s)",
           (pid,code,cont,orden))

    return jsonify(id=pid, numero=num)

@app.route("/api/proyectos/delete", methods=["POST"])
@login_required
def api_delete_proyecto():
    d = request.json or {}
    pid   = d.get("id")
    clave = d.get("clave","")
    if clave != "ELIMINAR2026":
        return jsonify(error="Clave incorrecta"), 403
    ex("DELETE FROM proyectos WHERE id=%s", (pid,))
    return jsonify(ok=True)

@app.route("/api/proyectos/update", methods=["POST"])
@login_required
def api_update_proyecto():
    d = request.json or {}
    pid = d.get("id")
    ex("""UPDATE proyectos SET nombre_proyecto=%s,empresa_cliente=%s,
          contacto_cliente=%s,telefono_cliente=%s,email_cliente=%s,
          atencion=%s,referencia=%s,descripcion_solucion=%s,
          fecha_creacion=%s,fecha_vencimiento=%s,tipo_cambio_usd=%s,
          carpeta_link=%s WHERE id=%s""",
       (d.get("nombre_proyecto"), d.get("empresa_cliente"),
        d.get("contacto_cliente"), d.get("telefono_cliente"),
        d.get("email_cliente"), d.get("atencion"), d.get("referencia"),
        d.get("descripcion_solucion"), d.get("fecha_creacion"),
        d.get("fecha_vencimiento"), d.get("tipo_cambio_usd") or 20,
        d.get("carpeta_link"), pid))
    _recalc_totals(pid)
    return jsonify(ok=True)

@app.route("/api/proyecto/<int:pid>")
@login_required
def api_get_proyecto(pid):
    proyecto = q("SELECT * FROM proyectos WHERE id=%s", (pid,), fetch="one")
    if not proyecto:
        return jsonify(error="No encontrado"), 404
    secciones = q("SELECT * FROM secciones WHERE proyecto_id=%s ORDER BY orden", (pid,))
    for s in secciones:
        if s["tipo"] == "mano_obra":
            s["partidas"] = list(q("SELECT * FROM partidas_mano_obra WHERE seccion_id=%s ORDER BY orden", (s["id"],)))
        else:
            s["partidas"] = list(q("SELECT * FROM partidas_equipo WHERE seccion_id=%s ORDER BY orden", (s["id"],)))
    condiciones = q("SELECT * FROM condiciones_comerciales WHERE proyecto_id=%s ORDER BY orden", (pid,))
    return jsonify(
        proyecto=_serialize(proyecto),
        secciones=[_serialize(s) for s in secciones],
        condiciones=list(condiciones)
    )


@app.route("/api/marcas")
@login_required
def api_marcas():
    categoria = request.args.get("categoria", "general")
    
    filas = q("""SELECT nombre FROM catalogo_marcas 
                 WHERE categoria=%s OR categoria='general' 
                 ORDER BY nombre ASC""", 
              (categoria,))
    
    lista_marcas = [fila["nombre"] for fila in filas]
    
    return jsonify(marcas=lista_marcas)

@app.route("/api/partidas/create", methods=["POST"])
@login_required
def api_create_partida():
    d = request.json or {}
    sid  = d.get("seccion_id")
    tipo = d.get("tipo","mano_obra")
    sec  = q("SELECT * FROM secciones WHERE id=%s", (sid,), fetch="one")
    if not sec:
        return jsonify(error="Sección no encontrada"), 404
    n = q("SELECT COUNT(*) cnt FROM partidas_mano_obra WHERE seccion_id=%s" if tipo=="mano_obra"
          else "SELECT COUNT(*) cnt FROM partidas_equipo WHERE seccion_id=%s", (sid,), fetch="one")["cnt"] + 1
    if tipo == "mano_obra":
        new_id = ex("INSERT INTO partidas_mano_obra (seccion_id,numero_partida,descripcion,horas_mo,dias_trabajo,costo_hora_usd,porcentaje_mgn,subtotal,total_usd,total_mn,orden) VALUES (%s,%s,'',0,1,0,0,0,0,0,%s)",
                    (sid, n, n))
    else:
        new_id = ex("INSERT INTO partidas_equipo (seccion_id,numero_partida,descripcion,marca,modelo,cantidad,precio_lista,moneda,porcentaje_mgn,subtotal,total_mn,total_usd,orden) VALUES (%s,%s,'','','',1,0,'MN',0,0,0,0,%s)",
                    (sid, n, n))
    return jsonify(id=new_id)

@app.route("/api/partidas/update", methods=["POST"])
@login_required
def api_update_partida():
    d  = request.json or {}
    pid = d.get("id")
    tipo = d.get("tipo","mano_obra")
    tc   = float(d.get("tipo_cambio",20) or 20)
    if tipo == "mano_obra":
        h = float(d.get("horas_mo") or 0)
        di = float(d.get("dias_trabajo") or 0)
        c  = float(d.get("costo_hora_usd") or 0)
        m  = float(d.get("porcentaje_mgn") or 0)
        sub = h * di * c
        t_usd = sub * (1 + m/100)
        t_mn  = t_usd * tc
        ex("""UPDATE partidas_mano_obra SET descripcion=%s,horas_mo=%s,dias_trabajo=%s,
              costo_hora_usd=%s,porcentaje_mgn=%s,subtotal=%s,total_usd=%s,total_mn=%s
              WHERE id=%s""",
           (d.get("descripcion",""), h, di, c, m, sub, t_usd, t_mn, pid))
        sec = q("SELECT seccion_id FROM partidas_mano_obra WHERE id=%s", (pid,), fetch="one")
    else:
        qty    = float(d.get("cantidad") or 0)
        precio = float(d.get("precio_lista") or 0)
        m      = float(d.get("porcentaje_mgn") or 0)
        moneda = d.get("moneda","MN")
        sub    = qty * precio
        if moneda == "USD":
            t_usd = sub * (1 + m/100)
            t_mn  = t_usd * tc
        else:
            t_mn  = sub * (1 + m/100)
            t_usd = t_mn / tc if tc else 0
        ex("""UPDATE partidas_equipo SET descripcion=%s,marca=%s,modelo=%s,
              cantidad=%s,precio_lista=%s,moneda=%s,porcentaje_mgn=%s,
              subtotal=%s,total_mn=%s,total_usd=%s WHERE id=%s""",
           (d.get("descripcion",""), d.get("marca",""), d.get("modelo",""),
            qty, precio, moneda, m, sub, t_mn, t_usd, pid))
        sec = q("SELECT seccion_id FROM partidas_equipo WHERE id=%s", (pid,), fetch="one")

    if sec:
        _recalc_section(sec["seccion_id"], tipo, tc)
        sec_row = q("SELECT proyecto_id FROM secciones WHERE id=%s", (sec["seccion_id"],), fetch="one")
        if sec_row:
            _recalc_totals(sec_row["proyecto_id"])
    return jsonify(ok=True)

@app.route("/api/partidas/delete", methods=["POST"])
@login_required
def api_delete_partida():
    d    = request.json or {}
    pid  = d.get("id")
    tipo = d.get("tipo","mano_obra")
    tc   = float(d.get("tipo_cambio",20) or 20)
    if tipo == "mano_obra":
        sec = q("SELECT seccion_id FROM partidas_mano_obra WHERE id=%s", (pid,), fetch="one")
        ex("DELETE FROM partidas_mano_obra WHERE id=%s", (pid,))
    else:
        sec = q("SELECT seccion_id FROM partidas_equipo WHERE id=%s", (pid,), fetch="one")
        ex("DELETE FROM partidas_equipo WHERE id=%s", (pid,))
    if sec:
        _recalc_section(sec["seccion_id"], tipo, tc)
        sr = q("SELECT proyecto_id FROM secciones WHERE id=%s", (sec["seccion_id"],), fetch="one")
        if sr:
            _recalc_totals(sr["proyecto_id"])
    return jsonify(ok=True)

@app.route("/api/condiciones/create", methods=["POST"])
@login_required
def api_create_cond():
    d = request.json or {}
    pid = d.get("proyecto_id")
    n = q("SELECT COUNT(*) cnt FROM condiciones_comerciales WHERE proyecto_id=%s", (pid,), fetch="one")["cnt"] + 1
    new_id = ex("INSERT INTO condiciones_comerciales (proyecto_id,codigo,contenido,orden) VALUES (%s,%s,%s,%s)",
                (pid, f"C{n}", "Nueva condición comercial.", n))
    return jsonify(id=new_id, codigo=f"C{n}")

@app.route("/api/condiciones/update", methods=["POST"])
@login_required
def api_update_cond():
    d = request.json or {}
    ex("UPDATE condiciones_comerciales SET codigo=%s,contenido=%s WHERE id=%s",
       (d.get("codigo"), d.get("contenido"), d.get("id")))
    return jsonify(ok=True)

@app.route("/api/condiciones/delete", methods=["POST"])
@login_required
def api_delete_cond():
    ex("DELETE FROM condiciones_comerciales WHERE id=%s", (request.json.get("id"),))
    return jsonify(ok=True)

@app.route("/api/cuenta/update", methods=["POST"])
@login_required
def api_update_cuenta():
    d = request.json or {}
    user = q("SELECT * FROM usuarios WHERE id=%s", (session["user_id"],), fetch="one")
    if not verify_pw(d.get("current_password",""), user["password_hash"]):
        return jsonify(error="Contraseña actual incorrecta"), 400
    if d.get("new_email"):
        ex("UPDATE usuarios SET email=%s WHERE id=%s", (d["new_email"], session["user_id"]))
        session["user_email"] = d["new_email"]
    if d.get("new_password"):
        ex("UPDATE usuarios SET password_hash=%s WHERE id=%s",
           (hash_pw(d["new_password"]), session["user_id"]))
    return jsonify(ok=True)

@app.route("/api/proyecto/<int:pid>/pdf")
@login_required
def api_pdf(pid):
    proyecto   = q("SELECT * FROM proyectos WHERE id=%s", (pid,), fetch="one")
    secciones  = q("SELECT * FROM secciones WHERE proyecto_id=%s ORDER BY orden", (pid,))
    condiciones= q("SELECT * FROM condiciones_comerciales WHERE proyecto_id=%s ORDER BY orden", (pid,))
    try:
        from fpdf import FPDF
        pdf = _build_pdf(proyecto, secciones, condiciones)
        buf = io.BytesIO()
        pdf.output(buf)
        buf.seek(0)
        filename = f"COT_{proyecto.get('numero_proyecto','')}.pdf"
        return send_file(buf, as_attachment=True, download_name=filename, mimetype="application/pdf")
    except Exception as e:
        return jsonify(error=str(e)), 500

def _serialize(row):
    if not row:
        return row
    out = {}
    for k, v in row.items():
        if isinstance(v, (date, datetime)):
            out[k] = str(v)
        else:
            out[k] = v
    return out

def _recalc_section(sid, tipo, tc=20):
    if tipo == "mano_obra":
        rows = q("SELECT total_mn,total_usd FROM partidas_mano_obra WHERE seccion_id=%s",(sid,))
    else:
        rows = q("SELECT total_mn,total_usd FROM partidas_equipo WHERE seccion_id=%s",(sid,))
    tmn  = sum(float(r.get("total_mn") or 0) for r in rows)
    tusd = sum(float(r.get("total_usd") or 0) for r in rows)
    ex("UPDATE secciones SET subtotal_mn=%s,subtotal_usd=%s WHERE id=%s",(tmn,tusd,sid))

def _recalc_totals(pid):
    rows = q("SELECT subtotal_mn,subtotal_usd FROM secciones WHERE proyecto_id=%s",(pid,))
    tmn  = sum(float(r.get("subtotal_mn") or 0) for r in rows)
    tusd = sum(float(r.get("subtotal_usd") or 0) for r in rows)
    ex("UPDATE proyectos SET total_mn=%s,total_usd=%s WHERE id=%s",(tmn,tusd,pid))

def _build_pdf(proyecto, secciones, condiciones):
    from fpdf import FPDF
    from utils.numero_a_letras import numero_a_letras
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    BLUE = (37, 99, 235)
    DARK = (15, 23, 42)
    GRAY = (100, 116, 139)
    pdf.set_fill_color(*BLUE)
    pdf.rect(0, 0, 210, 38, "F")
    pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",20)
    pdf.set_xy(12,8)
    pdf.cell(0,8,"DEMATIQ AUTOMATIZACIÓN")
    pdf.set_font("Helvetica","",9)
    pdf.set_xy(12,20)
    pdf.cell(0,5,"Sistema de Cotizaciones Profesional")
    pdf.set_font("Helvetica","B",11)
    pdf.set_xy(130,10)
    pdf.cell(0,6,f"COT. No. {proyecto.get('numero_proyecto','---')}")
    pdf.set_font("Helvetica","",9)
    pdf.set_xy(130,18)
    pdf.cell(0,5,f"Fecha: {str(proyecto.get('fecha_creacion',''))[:10]}")
    pdf.set_text_color(*DARK)
    pdf.set_xy(0,45)
    def sec_title(t):
        pdf.set_fill_color(*BLUE)
        pdf.set_text_color(255,255,255)
        pdf.set_font("Helvetica","B",10)
        pdf.cell(0,8,f"  {t}",ln=True,fill=True)
        pdf.set_text_color(*DARK)
        pdf.ln(2)
    def info(lbl,val):
        pdf.set_font("Helvetica","B",9)
        pdf.set_text_color(*GRAY)
        pdf.cell(45,6,lbl.upper()+":",ln=False)
        pdf.set_font("Helvetica","",9)
        pdf.set_text_color(*DARK)
        pdf.multi_cell(0,6,str(val or "---"))
    sec_title("INFORMACIÓN DEL CLIENTE")
    info("Empresa",proyecto.get("empresa_cliente"))
    info("Atención",proyecto.get("atencion"))
    info("Teléfono",proyecto.get("telefono_cliente"))
    info("Email",proyecto.get("email_cliente"))
    info("Referencia",proyecto.get("referencia"))
    pdf.ln(4)
    sec_title("RESUMEN DE COTIZACIÓN")
    tc = float(proyecto.get("tipo_cambio_usd") or 20)
    cw=[80,55,55]
    pdf.set_fill_color(239,246,255)
    pdf.set_font("Helvetica","B",9)
    for i,(h,w) in enumerate(zip(["SECCIÓN","TOTAL MN","TOTAL USD"],cw)):
        pdf.cell(w,7,h,border=1,fill=True,align="R" if i>0 else "L")
    pdf.ln()
    tmn_total=tusd_total=0
    alt=False
    for s in secciones:
        if s["codigo"] in("PRESE","REPORTE","CONDICIONES"):
            continue
        mn=float(s.get("subtotal_mn") or 0)
        usd=float(s.get("subtotal_usd") or 0)
        tmn_total+=mn; tusd_total+=usd
        pdf.set_fill_color(248,250,252) if alt else pdf.set_fill_color(255,255,255)
        pdf.set_font("Helvetica","",9)
        pdf.cell(cw[0],6,s.get("titulo","---"),border=1,fill=True)
        pdf.cell(cw[1],6,f"$ {mn:,.2f}",border=1,fill=True,align="R")
        pdf.cell(cw[2],6,f"$ {usd:,.2f}",border=1,fill=True,align="R")
        pdf.ln(); alt=not alt
    pdf.set_fill_color(*BLUE); pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",9)
    pdf.cell(cw[0],7,"TOTAL GENERAL",border=1,fill=True)
    pdf.cell(cw[1],7,f"$ {tmn_total:,.2f}",border=1,fill=True,align="R")
    pdf.cell(cw[2],7,f"$ {tusd_total:,.2f}",border=1,fill=True,align="R")
    pdf.ln(); pdf.set_text_color(*DARK); pdf.ln(4)
    iva=tmn_total*0.16; total_final=tmn_total+iva
    pdf.set_font("Helvetica","",9)
    pdf.cell(80,6,"Subtotal MN:",border=1); pdf.cell(0,6,f"$ {tmn_total:,.2f}",border=1,align="R",ln=True)
    pdf.cell(80,6,"IVA (16%):",border=1);   pdf.cell(0,6,f"$ {iva:,.2f}",border=1,align="R",ln=True)
    pdf.set_fill_color(*BLUE); pdf.set_text_color(255,255,255)
    pdf.set_font("Helvetica","B",10)
    pdf.cell(80,8,"TOTAL CON IVA:",border=1,fill=True)
    pdf.cell(0,8,f"$ {total_final:,.2f} M.N.",border=1,fill=True,align="R",ln=True)
    pdf.set_text_color(*GRAY); pdf.set_font("Helvetica","I",8)
    try:
        from utils.numero_a_letras import numero_a_letras
        pdf.ln(3); pdf.multi_cell(0,4,f"SON: {numero_a_letras(total_final)}")
    except Exception:
        pass
    pdf.set_text_color(*DARK); pdf.ln(6)
    if condiciones:
        sec_title("CONDICIONES COMERCIALES")
        for c in condiciones:
            pdf.set_font("Helvetica","B",9); pdf.cell(20,5,c.get("codigo",""),ln=False)
            pdf.set_font("Helvetica","",9);  pdf.multi_cell(0,5,c.get("contenido",""))
            pdf.ln(1)
    return pdf

if __name__ == "__main__":
    import webbrowser, threading
    def _open():
        import time; time.sleep(1.2)
        webbrowser.open("http://localhost:5000")
    threading.Thread(target=_open, daemon=True).start()
    app.run(debug=False, port=5000)
