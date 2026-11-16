# SERVIEXPRESS · Sistema Web de Gestión para Taller Mecánico

Aplicación web desarrollada en **Python (Flask + SQLite + Bootstrap 5)** que implementa todos los perfiles de usuario y reglas de negocio de la **ERS 3.9** e **Informe N.º 2**.

## Cómo ejecutar en Visual Studio Code (VS Code)

1. Descomprime esta carpeta y ábrela en **VS Code** (`Archivo > Abrir carpeta`).
2. Abre una terminal en VS Code (`Ctrl + ñ` o `Terminal > Nueva terminal`).
3. Instala Flask ejecutando:
   ```bash
   pip install -r requirements.txt
   ```
4. Inicia el servidor web ejecutando:
   ```bash
   python app.py
   ```
5. Abre tu navegador en: **http://127.0.0.1:5000**

## Credenciales de prueba (Todos los perfiles)
La contraseña para todos los usuarios precargados es **`1234`**:
- **`admin`** → Administrador (Acceso completo, pagos, SII, reversas, informes, bitácora)
- **`mecanico1`** → Mecánico (Registrar servicios con o sin reserva, ver clientes/agenda)
- **`compras1`** → Encargado de compras (Emitir órdenes de pedido, informe RF-43)
- **`bodega1`** → Bodeguero (Recepcionar productos contra orden sin excedentes)
- **`dueno`** → Propietario/representante (Consulta de informes ejecutivos)
- **`jperez`** → Cliente registrado (Reservar horas, cancelar antes de inicio, ver mi historial)
