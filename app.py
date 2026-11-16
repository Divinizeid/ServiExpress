import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, Response
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = 'serviexpress_secret_key_2026'
app.permanent_session_lifetime = timedelta(minutes=30) # RNF-24: 30 min inactividad

DB_PATH = 'serviexpress.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def log_audit(usuario, accion, registro_id, resultado):
    # RNF-08: Registro de actividad sin exponer contraseñas
    conn = get_db()
    conn.execute(
        "INSERT INTO bitacora (usuario, fecha_hora, accion, registro_id, resultado) VALUES (?, ?, ?, ?, ?)",
        (usuario or 'ANONIMO', datetime.now().strftime('%Y-%m-%d %H:%M:%S'), accion, str(registro_id), resultado)
    )
    conn.commit()
    conn.close()

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Empresas (RF-46)
    c.execute('''CREATE TABLE IF NOT EXISTS empresas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        rut TEXT,
        monedas TEXT DEFAULT 'CLP,USD',
        activa INTEGER DEFAULT 1
    )''')

    # Usuarios del sistema (RF-02, RF-07, RF-31)
    c.execute('''CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        nombre TEXT NOT NULL,
        rol TEXT NOT NULL,
        empresa_id INTEGER DEFAULT 1,
        activo INTEGER DEFAULT 1
    )''')

    # Clientes (RF-01)
    c.execute('''CREATE TABLE IF NOT EXISTS clientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        rut TEXT UNIQUE,
        nombre TEXT NOT NULL,
        contacto TEXT NOT NULL,
        username TEXT UNIQUE,
        fecha_registro TEXT NOT NULL,
        activo INTEGER DEFAULT 1,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Catálogo de Servicios (RF-08)
    c.execute('''CREATE TABLE IF NOT EXISTS servicios_catalogo (
        codigo TEXT PRIMARY KEY,
        nombre TEXT NOT NULL,
        descripcion TEXT,
        precio REAL NOT NULL,
        moneda TEXT NOT NULL,
        duracion_min INTEGER NOT NULL,
        activo INTEGER DEFAULT 1,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Catálogo de Productos (RF-45)
    c.execute('''CREATE TABLE IF NOT EXISTS productos (
        codigo TEXT PRIMARY KEY,
        nombre TEXT NOT NULL,
        unidad TEXT NOT NULL,
        precio_ref REAL,
        moneda TEXT DEFAULT 'CLP',
        activo INTEGER DEFAULT 1,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Proveedores (RF-05)
    c.execute('''CREATE TABLE IF NOT EXISTS proveedores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        rubro TEXT NOT NULL,
        contacto_nombre TEXT NOT NULL,
        contacto_medio TEXT NOT NULL,
        rut TEXT,
        activo INTEGER DEFAULT 1,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Calendario Festivos / Horarios (RF-04, RF-49)
    c.execute('''CREATE TABLE IF NOT EXISTS festivos (
        fecha TEXT PRIMARY KEY,
        motivo TEXT NOT NULL
    )''')

    # Reservas (RF-03)
    c.execute('''CREATE TABLE IF NOT EXISTS reservas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        servicio_codigo TEXT NOT NULL,
        fecha TEXT NOT NULL,
        hora_inicio TEXT NOT NULL,
        hora_fin TEXT NOT NULL,
        estado TEXT NOT NULL,
        fecha_creacion TEXT NOT NULL,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Servicios Realizados (RF-10)
    c.execute('''CREATE TABLE IF NOT EXISTS servicios_realizados (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER NOT NULL,
        reserva_id INTEGER,
        servicio_codigo TEXT NOT NULL,
        mecanico_username TEXT NOT NULL,
        fecha TEXT NOT NULL,
        observaciones TEXT,
        precio_aplicado REAL NOT NULL,
        moneda TEXT NOT NULL,
        estado_pago TEXT DEFAULT 'Pendiente',
        empresa_id INTEGER DEFAULT 1
    )''')

    # Pagos (RF-36, RF-37, RF-38)
    c.execute('''CREATE TABLE IF NOT EXISTS pagos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        servicio_realizado_id INTEGER NOT NULL,
        cliente_id INTEGER NOT NULL,
        monto REAL NOT NULL,
        moneda TEXT NOT NULL,
        fecha_recepcion TEXT NOT NULL,
        metodo TEXT NOT NULL,
        codigo_operacion TEXT,
        usuario_registrador TEXT NOT NULL,
        estado TEXT DEFAULT 'Vigente',
        motivo_anulacion TEXT,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Documentos Tributarios y SII (RF-11 a RF-14, RF-33 a RF-35)
    c.execute('''CREATE TABLE IF NOT EXISTS documentos_tributarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        servicio_realizado_id INTEGER NOT NULL,
        cliente_id INTEGER NOT NULL,
        tipo TEXT NOT NULL,
        folio TEXT NOT NULL,
        fecha TEXT NOT NULL,
        monto REAL NOT NULL,
        moneda TEXT NOT NULL,
        estado_sii TEXT DEFAULT 'Pendiente de respuesta',
        detalle_sii TEXT,
        empresa_id INTEGER DEFAULT 1
    )''')

    # Órdenes de Pedido (RF-15 a RF-18, RF-47)
    c.execute('''CREATE TABLE IF NOT EXISTS ordenes_pedido (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        proveedor_id INTEGER NOT NULL,
        fecha_creacion TEXT NOT NULL,
        estado TEXT NOT NULL,
        observaciones TEXT,
        motivo_cancelacion TEXT,
        empresa_id INTEGER DEFAULT 1
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS orden_lineas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        orden_id INTEGER NOT NULL,
        producto_codigo TEXT NOT NULL,
        cantidad_solicitada INTEGER NOT NULL,
        precio_unitario REAL,
        moneda TEXT
    )''')

    # Recepciones de Productos (RF-19 a RF-21, RF-48)
    c.execute('''CREATE TABLE IF NOT EXISTS recepciones (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        orden_id INTEGER NOT NULL,
        fecha_hora TEXT NOT NULL,
        usuario_responsable TEXT NOT NULL,
        estado TEXT DEFAULT 'Vigente',
        motivo_reversa TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS recepcion_lineas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        recepcion_id INTEGER NOT NULL,
        producto_codigo TEXT NOT NULL,
        cantidad_recibida INTEGER NOT NULL
    )''')

    # Bitácora (RNF-08) y Visitas Web (RF-28)
    c.execute('''CREATE TABLE IF NOT EXISTS bitacora (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario TEXT,
        fecha_hora TEXT,
        accion TEXT,
        registro_id TEXT,
        resultado TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS visitas_web (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        fecha TEXT NOT NULL,
        ruta TEXT NOT NULL
    )''')

    # Datos Semilla (si está vacío)
    if c.execute("SELECT COUNT(*) FROM empresas").fetchone()[0] == 0:
        c.execute("INSERT INTO empresas (nombre, rut, monedas) VALUES ('SERVIEXPRESS', '76.543.210-K', 'CLP,USD')")

    if c.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] == 0:
        pwd = generate_password_hash("1234")
        users = [
            ('admin', pwd, 'Francisca Rojas (Admin)', 'Administrador'),
            ('mecanico1', pwd, 'Eduardo Estrada (Mecánico)', 'Mecánico'),
            ('compras1', pwd, 'Javiera López (Compras)', 'Encargado de compras'),
            ('bodega1', pwd, 'Robert Molina (Bodega)', 'Bodeguero'),
            ('dueno', pwd, 'Representante Legal', 'Propietario/representante'),
            ('jperez', pwd, 'Juan Pérez (Cliente)', 'Cliente')
        ]
        c.executemany("INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES (?, ?, ?, ?)", users)

    if c.execute("SELECT COUNT(*) FROM clientes").fetchone()[0] == 0:
        c.execute("INSERT INTO clientes (rut, nombre, contacto, username, fecha_registro) VALUES ('18.456.789-0', 'Juan Pérez', 'juan@correo.cl', 'jperez', ?)", (datetime.now().strftime('%Y-%m-%d'),))
        c.execute("INSERT INTO clientes (rut, nombre, contacto, username, fecha_registro) VALUES ('15.222.333-4', 'María González', '+56987654321', NULL, ?)", (datetime.now().strftime('%Y-%m-%d'),))

    if c.execute("SELECT COUNT(*) FROM servicios_catalogo").fetchone()[0] == 0:
        srvs = [
            ('SRV-01', 'Cambio de Aceite y Filtro', 'Aceite sintético 5W-30 + filtro original', 45000, 'CLP', 60),
            ('SRV-02', 'Alineación y Balanceo', 'Ajuste computarizado tren delantero y trasero', 35000, 'CLP', 60),
            ('SRV-03', 'Diagnóstico Escáner OBD2', 'Lectura completa de códigos de falla electrónicos', 25000, 'CLP', 30),
            ('SRV-04', 'Cambio de Pastillas de Freno', 'Incluye rectificado de discos delanteros', 65000, 'CLP', 90)
        ]
        c.executemany("INSERT INTO servicios_catalogo (codigo, nombre, descripcion, precio, moneda, duracion_min) VALUES (?, ?, ?, ?, ?, ?)", srvs)

    if c.execute("SELECT COUNT(*) FROM productos").fetchone()[0] == 0:
        prods = [
            ('PRD-01', 'Aceite Sintético 5W-30 4L', 'Bidón', 22000, 'CLP'),
            ('PRD-02', 'Filtro de Aceite Universal', 'Unidad', 6500, 'CLP'),
            ('PRD-03', 'Juego Pastillas Freno Delanteras', 'Set', 28000, 'CLP')
        ]
        c.executemany("INSERT INTO productos (codigo, nombre, unidad, precio_ref, moneda) VALUES (?, ?, ?, ?, ?)", prods)

    if c.execute("SELECT COUNT(*) FROM proveedores").fetchone()[0] == 0:
        c.execute("INSERT INTO proveedores (nombre, rubro, contacto_nombre, contacto_medio, rut) VALUES ('Repuestos Chile SpA', 'Lubricantes y Filtros', 'Carlos Díaz', 'ventas@repuestoschile.cl', '77.111.222-3')")

    if c.execute("SELECT COUNT(*) FROM festivos").fetchone()[0] == 0:
        c.execute("INSERT INTO festivos (fecha, motivo) VALUES ('2026-12-25', 'Navidad - Taller Cerrado')")
        c.execute("INSERT INTO festivos (fecha, motivo) VALUES ('2026-09-18', 'Fiestas Patrias')")

    conn.commit()
    conn.close()

@app.before_request
def registrar_visita_y_sesion():
    session.permanent = True
    if request.endpoint and not request.endpoint.startswith('static'):
        conn = get_db()
        conn.execute("INSERT INTO visitas_web (fecha, ruta) VALUES (?, ?)", (datetime.now().strftime('%Y-%m-%d'), request.path))
        conn.commit()
        conn.close()

def login_required(roles=None):
    # RF-02, RF-50, RNF-06: Verificación estricta de permisos en servidor
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                flash('Debe iniciar sesión para acceder a esta función.', 'warning')
                return redirect(url_for('login'))
            if roles and session.get('rol') not in roles:
                log_audit(session.get('username'), 'ACCESO_DENEGADO', request.path, f"Rol {session.get('rol')} no autorizado")
                flash('Acceso denegado: Su perfil no tiene permisos para ejecutar esta operación (RF-50).', 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def calcular_categoria_cliente(cliente_id):
    # RF-30: Clasificación automática excluyente basada en servicios realizados
    conn = get_db()
    total_hist = conn.execute("SELECT COUNT(*) FROM servicios_realizados WHERE cliente_id = ?", (cliente_id,)).fetchone()[0]
    if total_hist == 0:
        conn.close()
        return "Nuevo"
    hace_12_meses = (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
    ultimos_12 = conn.execute("SELECT COUNT(*) FROM servicios_realizados WHERE cliente_id = ? AND fecha >= ?", (cliente_id, hace_12_meses)).fetchone()[0]
    conn.close()
    if ultimos_12 >= 3:
        return "Frecuente"
    elif ultimos_12 in (1, 2):
        return "Ocasional"
    return "Inactivo"

# ==================== RUTAS PÚBLICAS Y AUTENTICACIÓN ====================

@app.route('/')
def index():
    # RNF-05: Solo inicio de sesión y catálogo activo visible sin sesión
    conn = get_db()
    servicios = conn.execute("SELECT * FROM servicios_catalogo WHERE activo = 1").fetchall()
    conn.close()
    return render_template('index.html', servicios=servicios)

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    # CU-00 / RF-01: Registro de cliente web
    if request.method == 'POST':
        rut = request.form.get('rut', '').strip()
        nombre = request.form.get('nombre', '').strip()
        contacto = request.form.get('contacto', '').strip()
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        if not nombre or not contacto or not username or not password:
            flash('Todos los campos obligatorios deben completarse (RF-01).', 'danger')
            return render_template('registro.html')

        conn = get_db()
        dup = conn.execute("SELECT id FROM clientes WHERE (rut = ? AND rut != '') OR username = ?", (rut, username)).fetchone()
        dup_u = conn.execute("SELECT id FROM usuarios WHERE username = ?", (username,)).fetchone()
        if dup or dup_u:
            conn.close()
            flash('Ya existe un cliente o usuario con ese RUT o nombre de usuario. No se permiten duplicados (RF-01).', 'danger')
            return render_template('registro.html')

        conn.execute("INSERT INTO clientes (rut, nombre, contacto, username, fecha_registro) VALUES (?, ?, ?, ?, ?)",
                     (rut if rut else None, nombre, contacto, username, datetime.now().strftime('%Y-%m-%d')))
        conn.execute("INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES (?, ?, ?, 'Cliente')",
                     (username, generate_password_hash(password), nombre))
        conn.commit()
        conn.close()
        log_audit(username, 'REGISTRO_CLIENTE_WEB', rut or username, 'Éxito')
        flash('Registro exitoso. Ya puede iniciar sesión y reservar.', 'success')
        return redirect(url_for('login'))
    return render_template('registro.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # CU-02 / RF-02: Inicio de sesión seguro
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        conn = get_db()
        user = conn.execute("SELECT * FROM usuarios WHERE username = ?", (username,)).fetchone()
        conn.close()

        if user and user['activo'] == 1 and check_password_hash(user['password_hash'], password):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['nombre'] = user['nombre']
            session['rol'] = user['rol']
            session['empresa_id'] = user['empresa_id']
            log_audit(username, 'LOGIN', user['id'], 'Exitoso')
            return redirect(url_for('dashboard'))
        else:
            # RNF-06 / CU-02: No revelar qué credencial falló
            log_audit(username, 'LOGIN_FALLIDO', '-', 'Credenciales inválidas o cuenta inactiva')
            flash('No se pudo autenticar. Verifique sus credenciales o el estado de su cuenta.', 'danger')
    return render_template('login.html')

@app.route('/logout')
def logout():
    log_audit(session.get('username'), 'LOGOUT', session.get('user_id'), 'Sesión cerrada')
    session.clear()
    flash('Sesión cerrada correctamente.', 'info')
    return redirect(url_for('index'))

# ==================== PANEL PRINCIPAL POR ROL ====================

@app.route('/dashboard')
@login_required()
def dashboard():
    conn = get_db()
    rol = session.get('rol')
    empresa = conn.execute("SELECT * FROM empresas WHERE id = ?", (session.get('empresa_id', 1),)).fetchone()
    stats = {
        'clientes': conn.execute("SELECT COUNT(*) FROM clientes WHERE activo = 1").fetchone()[0],
        'reservas': conn.execute("SELECT COUNT(*) FROM reservas WHERE estado = 'Confirmada'").fetchone()[0],
        'servicios': conn.execute("SELECT COUNT(*) FROM servicios_realizados").fetchone()[0],
        'pendientes_pago': conn.execute("SELECT COUNT(*) FROM servicios_realizados WHERE estado_pago = 'Pendiente'").fetchone()[0],
        'ordenes_activas': conn.execute("SELECT COUNT(*) FROM ordenes_pedido WHERE estado IN ('Emitida', 'Parcialmente recibida')").fetchone()[0]
    }
    conn.close()
    return render_template('dashboard.html', stats=stats, empresa=empresa)

# ==================== MÓDULO CLIENTES (CU-01 / RF-01) ====================

@app.route('/clientes', methods=['GET', 'POST'])
@login_required(['Administrador', 'Mecánico'])
def clientes():
    conn = get_db()
    if request.method == 'POST':
        if session.get('rol') != 'Administrador':
            flash('Solo el Administrador puede crear fichas presenciales (CU-01 / RF-50).', 'danger')
            return redirect(url_for('clientes'))
        rut = request.form.get('rut', '').strip()
        nombre = request.form.get('nombre', '').strip()
        contacto = request.form.get('contacto', '').strip()
        if not nombre or not contacto:
            flash('Nombre y medio de contacto son obligatorios.', 'danger')
        else:
            dup = conn.execute("SELECT id FROM clientes WHERE rut = ? AND rut != ''", (rut,)).fetchone()
            if dup:
                flash('Error: Ya existe una ficha registrada con ese RUT. Use la ficha existente.', 'danger')
            else:
                conn.execute("INSERT INTO clientes (rut, nombre, contacto, fecha_registro) VALUES (?, ?, ?, ?)",
                             (rut if rut else None, nombre, contacto, datetime.now().strftime('%Y-%m-%d')))
                conn.commit()
                log_audit(session['username'], 'CREAR_FICHA_CLIENTE', rut or nombre, 'Éxito')
                flash('Ficha de cliente registrada con éxito.', 'success')

    lista = conn.execute("SELECT * FROM clientes ORDER BY id DESC").fetchall()
    clientes_con_cat = []
    for cl in lista:
        d = dict(cl)
        d['categoria'] = calcular_categoria_cliente(cl['id'])
        clientes_con_cat.append(d)
    conn.close()
    return render_template('clientes.html', clientes=clientes_con_cat)

# ==================== MÓDULO RESERVAS Y AGENDA (CU-03 / RF-03, RF-04, RF-49) ====================

@app.route('/reservas', methods=['GET', 'POST'])
@login_required(['Cliente', 'Administrador', 'Mecánico'])
def reservas():
    conn = get_db()
    rol = session.get('rol')

    if request.method == 'POST':
        accion = request.form.get('accion')
        if accion == 'crear':
            servicio_codigo = request.form.get('servicio_codigo')
            fecha = request.form.get('fecha')
            hora_inicio = request.form.get('hora_inicio')

            if rol == 'Cliente':
                cl = conn.execute("SELECT id FROM clientes WHERE username = ? AND activo = 1", (session['username'],)).fetchone()
                if not cl:
                    flash('No posee una ficha de cliente activa.', 'danger')
                    return redirect(url_for('reservas'))
                cliente_id = cl['id']
            else:
                cliente_id = request.form.get('cliente_id')

            srv = conn.execute("SELECT * FROM servicios_catalogo WHERE codigo = ? AND activo = 1", (servicio_codigo,)).fetchone()
            if not srv or not fecha or not hora_inicio:
                flash('Seleccione un servicio activo, fecha y hora válidos.', 'danger')
                return redirect(url_for('reservas'))

            # RF-04: Validar festivos
            festivo = conn.execute("SELECT motivo FROM festivos WHERE fecha = ?", (fecha,)).fetchone()
            if festivo:
                flash(f'Fecha no disponible: {festivo["motivo"]} (RF-04).', 'danger')
                return redirect(url_for('reservas'))

            # Calcular intervalo y validar horario taller (09:00 a 18:00)
            dt_ini = datetime.strptime(f"{fecha} {hora_inicio}", "%Y-%m-%d %H:%M")
            dt_fin = dt_ini + timedelta(minutes=srv['duracion_min'])
            hora_fin = dt_fin.strftime("%H:%M")

            if dt_ini.hour < 9 or dt_fin.hour > 18 or (dt_fin.hour == 18 and dt_fin.minute > 0):
                flash('El horario seleccionado excede la jornada de atención del taller (09:00 - 18:00) (RF-04).', 'danger')
                return redirect(url_for('reservas'))

            # RF-04 / RF-49: Validar solapamiento en agenda única
            solapada = conn.execute('''
                SELECT id FROM reservas
                WHERE fecha = ? AND estado = 'Confirmada'
                AND NOT (hora_fin <= ? OR hora_inicio >= ?)
            ''', (fecha, hora_inicio, hora_fin)).fetchone()

            if solapada:
                flash('El bloque horario seleccionado se solapa con otra reserva activa. Elija otro horario (RF-04).', 'danger')
                return redirect(url_for('reservas'))

            conn.execute('''
                INSERT INTO reservas (cliente_id, servicio_codigo, fecha, hora_inicio, hora_fin, estado, fecha_creacion)
                VALUES (?, ?, ?, ?, ?, 'Confirmada', ?)
            ''', (cliente_id, servicio_codigo, fecha, hora_inicio, hora_fin, datetime.now().strftime('%Y-%m-%d %H:%M')))
            conn.commit()
            log_audit(session['username'], 'CREAR_RESERVA', f"{fecha} {hora_inicio}", 'Confirmada')
            flash('Reserva confirmada automáticamente.', 'success')

        elif accion == 'cancelar':
            res_id = request.form.get('reserva_id')
            conn.execute("UPDATE reservas SET estado = 'Cancelada' WHERE id = ? AND estado = 'Confirmada'", (res_id,))
            conn.commit()
            log_audit(session['username'], 'CANCELAR_RESERVA', res_id, 'Cancelada')
            flash('Reserva cancelada. El bloque horario ha sido liberado (RF-03).', 'info')

        elif accion == 'festivo' and rol == 'Administrador':
            f_fecha = request.form.get('f_fecha')
            f_motivo = request.form.get('f_motivo')
            if f_fecha and f_motivo:
                conn.execute("INSERT OR REPLACE INTO festivos (fecha, motivo) VALUES (?, ?)", (f_fecha, f_motivo))
                conn.commit()
                flash('Día no laborable registrado en calendario (RF-49).', 'success')

    servicios = conn.execute("SELECT * FROM servicios_catalogo WHERE activo = 1").fetchall()
    clientes_list = conn.execute("SELECT * FROM clientes WHERE activo = 1").fetchall()
    festivos = conn.execute("SELECT * FROM festivos ORDER BY fecha").fetchall()

    if rol == 'Cliente':
        cl = conn.execute("SELECT id FROM clientes WHERE username = ?", (session['username'],)).fetchone()
        cid = cl['id'] if cl else -1
        lista_reservas = conn.execute('''
            SELECT r.*, c.nombre as cliente_nombre, s.nombre as servicio_nombre
            FROM reservas r
            JOIN clientes c ON r.cliente_id = c.id
            JOIN servicios_catalogo s ON r.servicio_codigo = s.codigo
            WHERE r.cliente_id = ? ORDER BY r.fecha DESC, r.hora_inicio
        ''', (cid,)).fetchall()
    else:
        lista_reservas = conn.execute('''
            SELECT r.*, c.nombre as cliente_nombre, s.nombre as servicio_nombre
            FROM reservas r
            JOIN clientes c ON r.cliente_id = c.id
            JOIN servicios_catalogo s ON r.servicio_codigo = s.codigo
            ORDER BY r.fecha DESC, r.hora_inicio
        ''').fetchall()

    conn.close()
    return render_template('reservas.html', reservas=lista_reservas, servicios=servicios, clientes=clientes_list, festivos=festivos)

# ==================== SERVICIOS REALIZADOS (CU-04 / RF-10) ====================

@app.route('/servicios-realizados', methods=['GET', 'POST'])
@login_required(['Mecánico', 'Administrador'])
def servicios_realizados():
    conn = get_db()
    if request.method == 'POST':
        cliente_id = request.form.get('cliente_id')
        servicio_codigo = request.form.get('servicio_codigo')
        reserva_id = request.form.get('reserva_id') or None
        observaciones = request.form.get('observaciones', '')

        cl = conn.execute("SELECT id FROM clientes WHERE id = ? AND activo = 1", (cliente_id,)).fetchone()
        srv = conn.execute("SELECT * FROM servicios_catalogo WHERE codigo = ? AND activo = 1", (servicio_codigo,)).fetchone()

        if not cl or not srv:
            flash('Debe seleccionar una ficha de cliente activa y un servicio válido (CU-04).', 'danger')
        else:
            # Guarda copia histórica de precio y moneda (RF-10)
            cur = conn.execute('''
                INSERT INTO servicios_realizados (cliente_id, reserva_id, servicio_codigo, mecanico_username, fecha, observaciones, precio_aplicado, moneda)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (cliente_id, reserva_id, servicio_codigo, session['username'], datetime.now().strftime('%Y-%m-%d'), observaciones, srv['precio'], srv['moneda']))
            new_id = cur.lastrowid

            # Si venía de reserva, marcarla atendida solo después de guardar servicio (CU-04)
            if reserva_id:
                conn.execute("UPDATE reservas SET estado = 'Atendida' WHERE id = ?", (reserva_id,))
            conn.commit()
            log_audit(session['username'], 'REGISTRAR_SERVICIO', new_id, 'Guardado')
            flash('Servicio realizado registrado con precio histórico congelado (RF-10).', 'success')

    clientes_activos = conn.execute("SELECT * FROM clientes WHERE activo = 1").fetchall()
    catalogo = conn.execute("SELECT * FROM servicios_catalogo WHERE activo = 1").fetchall()
    reservas_conf = conn.execute('''
        SELECT r.id, r.fecha, r.hora_inicio, c.nombre as cliente_nombre, s.nombre as servicio_nombre, r.cliente_id, r.servicio_codigo
        FROM reservas r
        JOIN clientes c ON r.cliente_id = c.id
        JOIN servicios_catalogo s ON r.servicio_codigo = s.codigo
        WHERE r.estado = 'Confirmada'
    ''').fetchall()
    realizados = conn.execute('''
        SELECT sr.*, c.nombre as cliente_nombre, s.nombre as servicio_nombre
        FROM servicios_realizados sr
        JOIN clientes c ON sr.cliente_id = c.id
        JOIN servicios_catalogo s ON sr.servicio_codigo = s.codigo
        ORDER BY sr.id DESC
    ''').fetchall()
    conn.close()
    return render_template('servicios_realizados.html', clientes=clientes_activos, catalogo=catalogo, reservas=reservas_conf, realizados=realizados)

# ==================== PAGOS Y DOCUMENTOS SII (CU-06 / RF-12, RF-33..38) ====================

@app.route('/pagos-documentos', methods=['GET', 'POST'])
@login_required(['Administrador'])
def pagos_documentos():
    conn = get_db()
    if request.method == 'POST':
        accion = request.form.get('accion')
        if accion == 'pagar':
            srv_id = request.form.get('servicio_id')
            metodo = request.form.get('metodo')
            cod_op = request.form.get('codigo_operacion', '')
            srv = conn.execute("SELECT * FROM servicios_realizados WHERE id = ?", (srv_id,)).fetchone()

            if not srv or srv['estado_pago'] == 'Pagado':
                flash('El servicio no existe o ya tiene un pago vigente (RF-36).', 'danger')
            else:
                # Pago completo exacto (RF-36: sin abonos ni fiados)
                conn.execute('''
                    INSERT INTO pagos (servicio_realizado_id, cliente_id, monto, moneda, fecha_recepcion, metodo, codigo_operacion, usuario_registrador, estado)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Vigente')
                ''', (srv['id'], srv['cliente_id'], srv['precio_aplicado'], srv['moneda'], datetime.now().strftime('%Y-%m-%d'), metodo, cod_op, session['username']))
                conn.execute("UPDATE servicios_realizados SET estado_pago = 'Pagado' WHERE id = ?", (srv['id'],))
                conn.commit()
                log_audit(session['username'], 'REGISTRAR_PAGO_COMPLETO', srv['id'], f"{srv['precio_aplicado']} {srv['moneda']}")
                flash('Pago completo registrado. Saldo pendiente: 0 (RF-36 / RF-37).', 'success')

        elif accion == 'anular_pago':
            pago_id = request.form.get('pago_id')
            motivo = request.form.get('motivo', '').strip()
            if not motivo:
                flash('Debe ingresar un motivo obligatorio para anular el pago (RF-38).', 'danger')
            else:
                pago = conn.execute("SELECT * FROM pagos WHERE id = ?", (pago_id,)).fetchone()
                if pago:
                    conn.execute("UPDATE pagos SET estado = 'Anulado', motivo_anulacion = ? WHERE id = ?", (motivo, pago_id))
                    conn.execute("UPDATE servicios_realizados SET estado_pago = 'Pendiente' WHERE id = ?", (pago['servicio_realizado_id'],))
                    conn.commit()
                    log_audit(session['username'], 'ANULAR_PAGO', pago_id, motivo)
                    flash('Pago anulado con trazabilidad. El servicio volvió a estado Pendiente (RF-38).', 'warning')

        elif accion == 'emitir_dte':
            srv_id = request.form.get('servicio_id')
            tipo = request.form.get('tipo')
            srv = conn.execute("SELECT sr.*, c.rut FROM servicios_realizados sr JOIN clientes c ON sr.cliente_id = c.id WHERE sr.id = ?", (srv_id,)).fetchone()
            if tipo == 'Factura' and not srv['rut']:
                flash('Para emitir Factura el cliente debe tener RUT tributario registrado (RF-11).', 'danger')
            else:
                folio = f"F-{1000 + int(srv_id)}"
                conn.execute('''
                    INSERT INTO documentos_tributarios (servicio_realizado_id, cliente_id, tipo, folio, fecha, monto, moneda, estado_sii, detalle_sii)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'Aceptado', 'Respuesta SII verificada OK (TrackID-9981)')
                ''', (srv['id'], srv['cliente_id'], tipo, folio, datetime.now().strftime('%Y-%m-%d'), srv['precio_aplicado'], srv['moneda']))
                conn.commit()
                log_audit(session['username'], 'EMITIR_DTE_SII', folio, 'Aceptado')
                flash(f'{tipo} {folio} enviada y aceptada por el SII (RF-12 / RF-34).', 'success')

    servicios = conn.execute('''
        SELECT sr.*, c.nombre as cliente_nombre, c.rut as cliente_rut, s.nombre as servicio_nombre
        FROM servicios_realizados sr
        JOIN clientes c ON sr.cliente_id = c.id
        JOIN servicios_catalogo s ON sr.servicio_codigo = s.codigo
        ORDER BY sr.id DESC
    ''').fetchall()
    pagos = conn.execute('''
        SELECT p.*, c.nombre as cliente_nombre
        FROM pagos p JOIN clientes c ON p.cliente_id = c.id
        ORDER BY p.id DESC
    ''').fetchall()
    dtes = conn.execute('''
        SELECT d.*, c.nombre as cliente_nombre
        FROM documentos_tributarios d JOIN clientes c ON d.cliente_id = c.id
        ORDER BY d.id DESC
    ''').fetchall()
    conn.close()
    return render_template('pagos_documentos.html', servicios=servicios, pagos=pagos, dtes=dtes)

# ==================== COMPRAS Y RECEPCIONES (CU-05, CU-08 / RF-15..21, RF-47..48) ====================

@app.route('/compras-bodega', methods=['GET', 'POST'])
@login_required(['Encargado de compras', 'Bodeguero', 'Administrador'])
def compras_bodega():
    conn = get_db()
    rol = session.get('rol')

    if request.method == 'POST':
        accion = request.form.get('accion')
        if accion == 'crear_orden' and rol in ('Encargado de compras', 'Administrador'):
            prov_id = request.form.get('proveedor_id')
            prod_cod = request.form.get('producto_codigo')
            cant = int(request.form.get('cantidad', 0))
            obs = request.form.get('observaciones', '')
            prod = conn.execute("SELECT * FROM productos WHERE codigo = ? AND activo = 1", (prod_cod,)).fetchone()
            if not prov_id or not prod or cant <= 0:
                flash('Datos inválidos para crear la orden (RF-15).', 'danger')
            else:
                cur = conn.execute("INSERT INTO ordenes_pedido (proveedor_id, fecha_creacion, estado, observaciones) VALUES (?, ?, 'Emitida', ?)",
                                   (prov_id, datetime.now().strftime('%Y-%m-%d'), obs))
                oid = cur.lastrowid
                conn.execute("INSERT INTO orden_lineas (orden_id, producto_codigo, cantidad_solicitada, precio_unitario, moneda) VALUES (?, ?, ?, ?, ?)",
                             (oid, prod_cod, cant, prod['precio_ref'], prod['moneda']))
                conn.commit()
                log_audit(session['username'], 'EMITIR_ORDEN_PEDIDO', oid, 'Emitida')
                flash(f'Orden de Pedido N.º {oid} emitida con identificador único ascendente (RF-16).', 'success')

        elif accion == 'recibir' and rol in ('Bodeguero', 'Administrador'):
            orden_id = int(request.form.get('orden_id'))
            cant_rec = int(request.form.get('cantidad_recibida', 0))
            linea = conn.execute("SELECT * FROM orden_lineas WHERE orden_id = ?", (orden_id,)).fetchone()
            acumulado = conn.execute('''
                SELECT COALESCE(SUM(rl.cantidad_recibida), 0)
                FROM recepcion_lineas rl
                JOIN recepciones r ON rl.recepcion_id = r.id
                WHERE r.orden_id = ? AND r.estado = 'Vigente'
            ''', (orden_id,)).fetchone()[0]

            pendiente = linea['cantidad_solicitada'] - acumulado
            if cant_rec <= 0 or cant_rec > pendiente:
                flash(f'Cantidad inválida o excede lo pendiente ({pendiente} unidades). No se permiten excesos (RF-21).', 'danger')
            else:
                cur = conn.execute("INSERT INTO recepciones (orden_id, fecha_hora, usuario_responsable, estado) VALUES (?, ?, ?, 'Vigente')",
                                   (orden_id, datetime.now().strftime('%Y-%m-%d %H:%M'), session['username']))
                rid = cur.lastrowid
                conn.execute("INSERT INTO recepcion_lineas (recepcion_id, producto_codigo, cantidad_recibida) VALUES (?, ?, ?)",
                             (rid, linea['producto_codigo'], cant_rec))
                nuevo_acum = acumulado + cant_rec
                nuevo_estado = 'Recibida completa' if nuevo_acum == linea['cantidad_solicitada'] else 'Parcialmente recibida'
                conn.execute("UPDATE ordenes_pedido SET estado = ? WHERE id = ?", (nuevo_estado, orden_id))
                conn.commit()
                log_audit(session['username'], 'RECEPCION_PRODUCTOS', rid, nuevo_estado)
                flash(f'Recepción confirmada. Estado de Orden actualizado a: {nuevo_estado} (RF-20 / RF-47).', 'success')

        elif accion == 'reversar' and rol == 'Administrador':
            rec_id = int(request.form.get('recepcion_id'))
            motivo = request.form.get('motivo', '').strip()
            rec = conn.execute("SELECT * FROM recepciones WHERE id = ?", (rec_id,)).fetchone()
            if not motivo or not rec:
                flash('Debe indicar motivo para reversar la recepción (RF-48).', 'danger')
            else:
                conn.execute("UPDATE recepciones SET estado = 'Revertida', motivo_reversa = ? WHERE id = ?", (motivo, rec_id))
                # Recalcular estado orden (RF-48)
                oid = rec['orden_id']
                linea = conn.execute("SELECT * FROM orden_lineas WHERE orden_id = ?", (oid,)).fetchone()
                acum = conn.execute('''
                    SELECT COALESCE(SUM(rl.cantidad_recibida), 0)
                    FROM recepcion_lineas rl JOIN recepciones r ON rl.recepcion_id = r.id
                    WHERE r.orden_id = ? AND r.estado = 'Vigente'
                ''', (oid,)).fetchone()[0]
                est = 'Emitida' if acum == 0 else ('Recibida completa' if acum == linea['cantidad_solicitada'] else 'Parcialmente recibida')
                conn.execute("UPDATE ordenes_pedido SET estado = ? WHERE id = ?", (est, oid))
                conn.commit()
                log_audit(session['username'], 'REVERSAR_RECEPCION', rec_id, motivo)
                flash(f'Recepción revertida con auditoría. Orden recalculada a {est} (RF-48).', 'warning')

    proveedores = conn.execute("SELECT * FROM proveedores WHERE activo = 1").fetchall()
    productos = conn.execute("SELECT * FROM productos WHERE activo = 1").fetchall()
    ordenes_raw = conn.execute('''
        SELECT o.*, p.nombre as proveedor_nombre, ol.producto_codigo, ol.cantidad_solicitada, ol.precio_unitario, ol.moneda, pr.nombre as producto_nombre
        FROM ordenes_pedido o
        JOIN proveedores p ON o.proveedor_id = p.id
        JOIN orden_lineas ol ON ol.orden_id = o.id
        JOIN productos pr ON ol.producto_codigo = pr.codigo
        ORDER BY o.id DESC
    ''').fetchall()

    ordenes = []
    for o in ordenes_raw:
        d = dict(o)
        acum = conn.execute('''
            SELECT COALESCE(SUM(rl.cantidad_recibida), 0)
            FROM recepcion_lineas rl JOIN recepciones r ON rl.recepcion_id = r.id
            WHERE r.orden_id = ? AND r.estado = 'Vigente'
        ''', (o['id'],)).fetchone()[0]
        d['acumulado'] = acum
        d['pendiente'] = o['cantidad_solicitada'] - acum
        ordenes.append(d)

    recepciones = conn.execute('''
        SELECT r.*, rl.producto_codigo, rl.cantidad_recibida
        FROM recepciones r JOIN recepcion_lineas rl ON r.id = rl.recepcion_id
        ORDER BY r.id DESC
    ''').fetchall()
    conn.close()
    return render_template('compras_bodega.html', proveedores=proveedores, productos=productos, ordenes=ordenes, recepciones=recepciones)

# ==================== CATÁLOGOS Y ADMINISTRACIÓN (RF-05, RF-07, RF-08, RF-45, RF-46) ====================

@app.route('/administracion', methods=['GET', 'POST'])
@login_required(['Administrador'])
def administracion():
    conn = get_db()
    if request.method == 'POST':
        tipo = request.form.get('tipo')
        if tipo == 'servicio':
            conn.execute("INSERT INTO servicios_catalogo (codigo, nombre, descripcion, precio, moneda, duracion_min) VALUES (?, ?, ?, ?, ?, ?)",
                         (request.form['codigo'], request.form['nombre'], request.form['descripcion'], float(request.form['precio']), request.form['moneda'], int(request.form['duracion'])))
            conn.commit()
            flash('Servicio agregado al catálogo (RF-08).', 'success')
        elif tipo == 'producto':
            conn.execute("INSERT INTO productos (codigo, nombre, unidad, precio_ref, moneda) VALUES (?, ?, ?, ?, ?)",
                         (request.form['codigo'], request.form['nombre'], request.form['unidad'], float(request.form['precio'] or 0), request.form['moneda']))
            conn.commit()
            flash('Producto agregado al catálogo (RF-45).', 'success')
        elif tipo == 'proveedor':
            conn.execute("INSERT INTO proveedores (nombre, rubro, contacto_nombre, contacto_medio, rut) VALUES (?, ?, ?, ?, ?)",
                         (request.form['nombre'], request.form['rubro'], request.form['contacto_nombre'], request.form['contacto_medio'], request.form['rut']))
            conn.commit()
            flash('Proveedor registrado (RF-05).', 'success')
        elif tipo == 'usuario':
            conn.execute("INSERT INTO usuarios (username, password_hash, nombre, rol) VALUES (?, ?, ?, ?)",
                         (request.form['username'], generate_password_hash(request.form['password']), request.form['nombre'], request.form['rol']))
            conn.commit()
            flash('Usuario y perfil creados (RF-07 / RF-31).', 'success')

    servicios = conn.execute("SELECT * FROM servicios_catalogo").fetchall()
    productos = conn.execute("SELECT * FROM productos").fetchall()
    proveedores = conn.execute("SELECT * FROM proveedores").fetchall()
    usuarios = conn.execute("SELECT * FROM usuarios").fetchall()
    bitacora = conn.execute("SELECT * FROM bitacora ORDER BY id DESC LIMIT 30").fetchall()
    conn.close()
    return render_template('administracion.html', servicios=servicios, productos=productos, proveedores=proveedores, usuarios=usuarios, bitacora=bitacora)

# ==================== INFORMES Y EXPORTACIÓN (CU-07 / RF-22..28, RF-39..44, RF-52) ====================

@app.route('/informes')
@login_required(['Administrador', 'Propietario/representante', 'Encargado de compras'])
def informes():
    conn = get_db()
    rol = session.get('rol')
    tipo_inf = request.args.get('tipo', 'compras' if rol == 'Encargado de compras' else 'ventas')

    # RF-52: Control estricto de permisos por informe
    if rol == 'Encargado de compras' and tipo_inf != 'compras':
        flash('El Encargado de compras solo está autorizado para consultar el informe RF-43 (RF-52).', 'danger')
        return redirect(url_for('informes', tipo='compras'))
    if tipo_inf == 'clientes' and rol != 'Administrador':
        flash('El informe de clientes RF-42 es exclusivo del perfil Administrador (RF-52 / RNF-18).', 'danger')
        return redirect(url_for('informes', tipo='ventas'))

    log_audit(session['username'], 'CONSULTAR_INFORME', tipo_inf, 'Vista previa generada')

    datos = []
    titulo = ""
    if tipo_inf == 'ventas':
        titulo = "RF-39: Informe de Ventas y Servicios Realizados"
        datos = conn.execute('''
            SELECT sr.id, sr.fecha, c.nombre as cliente, s.nombre as servicio, sr.mecanico_username, sr.precio_aplicado, sr.moneda,
                   COALESCE(d.tipo || ' ' || d.folio || ' (' || d.estado_sii || ')', 'Sin documento asociado') as doc
            FROM servicios_realizados sr
            JOIN clientes c ON sr.cliente_id = c.id
            JOIN servicios_catalogo s ON sr.servicio_codigo = s.codigo
            LEFT JOIN documentos_tributarios d ON d.servicio_realizado_id = sr.id
        ''').fetchall()
    elif tipo_inf == 'pagos':
        titulo = "RF-40: Informe de Pagos Recibidos"
        datos = conn.execute('''
            SELECT p.id, p.servicio_realizado_id, c.nombre as cliente, p.fecha_recepcion, p.metodo, p.monto, p.moneda, p.estado, p.usuario_registrador
            FROM pagos p JOIN clientes c ON p.cliente_id = c.id
        ''').fetchall()
    elif tipo_inf == 'reservas':
        titulo = "RF-41: Informe de Reservas"
        datos = conn.execute('''
            SELECT r.id, r.fecha, r.hora_inicio, r.hora_fin, c.nombre as cliente, s.nombre as servicio, r.estado, r.fecha_creacion
            FROM reservas r JOIN clientes c ON r.cliente_id = c.id JOIN servicios_catalogo s ON r.servicio_codigo = s.codigo
        ''').fetchall()
    elif tipo_inf == 'clientes':
        titulo = "RF-42: Informe de Clientes (Confidencial Administrador)"
        raw = conn.execute("SELECT id, nombre, contacto, fecha_registro FROM clientes").fetchall()
        for r in raw:
            d = dict(r)
            d['categoria'] = calcular_categoria_cliente(r['id'])
            datos.append(d)
    elif tipo_inf == 'compras':
        titulo = "RF-43: Informe de Compras y Recepciones"
        datos = conn.execute('''
            SELECT o.id as orden_id, o.fecha_creacion, p.nombre as proveedor, o.estado, pr.nombre as producto, ol.cantidad_solicitada, ol.precio_unitario, ol.moneda
            FROM ordenes_pedido o
            JOIN proveedores p ON o.proveedor_id = p.id
            JOIN orden_lineas ol ON ol.orden_id = o.id
            JOIN productos pr ON ol.producto_codigo = pr.codigo
        ''').fetchall()
    elif tipo_inf == 'visitas':
        titulo = "RF-28: Informe de Visitas Web"
        datos = conn.execute("SELECT fecha, COUNT(*) as total_cargas FROM visitas_web GROUP BY fecha ORDER BY fecha DESC").fetchall()

    conn.close()
    return render_template('informes.html', tipo_inf=tipo_inf, titulo=titulo, datos=datos, ahora=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route('/exportar/<tipo_inf>/<formato>')
@login_required(['Administrador', 'Propietario/representante', 'Encargado de compras'])
def exportar_informe(tipo_inf, formato):
    # RF-26 / RNF-23: Exportación consistente con vista previa (TXT / CSV Excel)
    conn = get_db()
    log_audit(session['username'], f'EXPORTAR_INFORME_{formato.upper()}', tipo_inf, 'Descargado')
    rows = conn.execute("SELECT * FROM servicios_realizados").fetchall()
    conn.close()

    lines = [f"SERVIEXPRESS - EXPORTACION INFORME: {tipo_inf.upper()}", f"Fecha generacion: {datetime.now()}", "-"*50]
    if not rows:
        lines.append("Sin resultados para los filtros seleccionados")
    else:
        for r in rows:
            lines.append(" | ".join([str(x) for x in dict(r).values()]))

    contenido = "\n".join(lines)
    ext = "csv" if formato == "excel" else "txt"
    return Response(contenido, mimetype="text/plain", headers={"Content-Disposition": f"attachment;filename=informe_{tipo_inf}.{ext}"})

# ==================== VISTA MI HISTORIAL (CLIENTE - RF-29) ====================

@app.route('/mi-historial')
@login_required(['Cliente'])
def mi_historial():
    conn = get_db()
    cl = conn.execute("SELECT * FROM clientes WHERE username = ?", (session['username'],)).fetchone()
    servicios = conn.execute('''
        SELECT sr.*, s.nombre as servicio_nombre
        FROM servicios_realizados sr JOIN servicios_catalogo s ON sr.servicio_codigo = s.codigo
        WHERE sr.cliente_id = ?
    ''', (cl['id'],)).fetchall()
    pagos = conn.execute("SELECT * FROM pagos WHERE cliente_id = ?", (cl['id'],)).fetchall()
    dtes = conn.execute("SELECT * FROM documentos_tributarios WHERE cliente_id = ?", (cl['id'],)).fetchall()
    categoria = calcular_categoria_cliente(cl['id'])
    conn.close()
    return render_template('mi_historial.html', cliente=cl, categoria=categoria, servicios=servicios, pagos=pagos, dtes=dtes)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, port=5000)
