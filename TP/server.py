
import socket
import subprocess
import threading
import time
import json
import pickle
import os

# Configuración del servidor
IP = "10.0.0.1"  # Escucha en todas las interfaces
PUERTO_NET_TASK = 50505
PUERTO_ALERT_FLOW = 12345
BUFFER_SIZE = 1024
NMS_AGENTS = 3
WAIT = 20
DIRECTORIO_DESTINO = "./archivos_recibidos"
DIRECTORIO_ALERTAS = "./alertas_recibidos"

barrera = threading.Barrier(2)

# Locks para evitar condiciones de carrera
file_lock = threading.Lock()
clientes_lock = threading.Lock()
tcp_lock = threading.Lock()

def main():
    os.makedirs(DIRECTORIO_DESTINO, exist_ok=True)
    os.makedirs(DIRECTORIO_ALERTAS, exist_ok=True)
    try:
        thread1 = threading.Thread(target=manejar_conexion_tcp, daemon=True)
        thread2 = threading.Thread(target=servidor_udp, daemon=True)
        thread3 = threading.Thread(target=start_iperf3_server, daemon=True)
        
        thread1.start()
        thread2.start()
        thread3.start()
        
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Cerrando el servidor...")

def servidor_udp():
    servidor = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor.bind((IP, PUERTO_NET_TASK))
    print("Servidor UDP escuchando en", IP, ":", PUERTO_NET_TASK, "...")

    clientes = {}
    while True:
        datos, direccion = servidor.recvfrom(BUFFER_SIZE)
        nombre_archivo = 'report_iperf'
        if datos.decode('utf-8') == 'guardar':
            tarea, dir = servidor.recvfrom(BUFFER_SIZE)
            if tarea  == 'PING':
                nombre_archivo = 'report_ping.txt'
            else:
                nombre_archivo = 'report_iperf.txt'
            rep, dir = servidor.recvfrom(BUFFER_SIZE)
            rep = rep.decode().strip()
            print(rep)
            if rep != None:
                ruta_completa = os.path.join(DIRECTORIO_DESTINO, nombre_archivo)

                # Guardar en el archivo
                with open(ruta_completa, "w", encoding="utf-8") as archivo:
                    archivo.write(rep)
                servidor.sendto(b'ACK', dir)
            else:
                servidor.sendto(b'FAIL', dir)
        else:
            print(f"[SERVIDOR] Mensaje recibido de {direccion}: {datos.decode()}")
            with clientes_lock:
                if direccion not in clientes:
                    print(f"[SERVIDOR] Nueva conexión detectada: {direccion}")
                    hilo_cliente = threading.Thread(
                        target=send_json,
                        args=(direccion, servidor),
                        daemon=True
                    )
                    hilo_cliente.start()
                    clientes[direccion] = hilo_cliente

def send_json(cliente_direccion, servidor):
    rout = cargar_metricas_router(cliente_direccion[0], "config.json")
    if not isinstance(rout, dict):
        rout = {"error": "No se encontraron métricas"}
    data_serializada = pickle.dumps(rout)
    servidor.sendto(data_serializada, cliente_direccion)

def manejar_conexion_tcp():
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_socket.bind((IP, PUERTO_ALERT_FLOW))
    tcp_socket.listen(NMS_AGENTS)
    print(f"Servidor TCP escuchando en {IP}:{PUERTO_ALERT_FLOW}...")
    while True:
        try:
            conn, addr = tcp_socket.accept()
            print(f"[SERVIDOR] Nueva conexión detectada: {addr}")
            hilo_cliente = threading.Thread(target=manejar_cliente, args=(conn, addr), daemon=True)
            hilo_cliente.start()
        except Exception as e:
            print(f"[SERVIDOR] Error al aceptar conexión: {e}")

def manejar_cliente(conn, addr):
    try:
        while True:
            data = conn.recv(1024)
            a = data.decode()
            if not data:
                break
            mut = f"[TCP] Mensaje recibido de {addr}: {a}"
            print(mut)
            file_name = "historal_alerts.txt"
            ruta_completa = os.path.join(DIRECTORIO_ALERTAS, file_name)

            # Guardar sin sobrescribir el contenido previo
            with open(ruta_completa, "a", encoding="utf-8") as archivo:  # 'a' para añadir sin sobrescribir
                archivo.write(f"\n{mut}")
            conn.sendall(b"Mensaje recibido en TCP")
    except Exception as e:
        print(f"Error en comunicación TCP con {addr}: {e}")
    finally:
        conn.close()

def cargar_metricas_router(ip, archivo="config.json"):
    try:
        with file_lock:
            with open(archivo, "r") as archivo_json:
                data = json.load(archivo_json)
        return next((device for device in data.get("devices", []) if ip in device.get("ips", [])), "Dispositivo no encontrado")
    except FileNotFoundError:
        print(f"Error: El archivo '{archivo}' no existe.")
    except json.JSONDecodeError:
        print("Error: El archivo JSON tiene un formato inválido.")
    except Exception as e:
        print(f"Error inesperado: {e}")

def start_iperf3_server(port=5201):
    try:
        print(f"Starting iperf3 server on port {port}...")
        subprocess.Popen(["iperf3", "-s", "-p", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception as e:
        print(f"Error starting iperf3 server: {e}")

if __name__ == "__main__":
    main()
