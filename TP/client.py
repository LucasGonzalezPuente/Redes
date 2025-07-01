import socket
import threading
import time
import subprocess
import os
import json
import re
import pickle
import psutil
import queue

# Configuración del cliente
IP_SERVIDOR = "10.0.0.1"
PUERTO_NET_TASK = 50505
PUERTO_ALERT_FLOW = 12345
WAIT = 1
BUFFER_SIZE = 1024
MAX_RETRIES = 5

# Crear evento y locks
evento = threading.Event()
evento_lock = threading.Lock()
archivo_lock = threading.Lock()
tcp_lock = threading.Lock()
cola = queue.Queue()
SIN_DATO = object()  # Marcador para indicar que no hay dato a pasar
# Variable compartida protegida por lock
dato = None

def main():
    thread1 = threading.Thread(target=enviar_alerta_tcp, daemon=True)
    thread2 = threading.Thread(target=cliente_udp, daemon=True)
    
    thread1.start()
    thread2.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Cerrando el cliente...")

def cliente_udp():
    global dato
    print("Iniciando cliente UDP")
    cliente = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    servidor = (IP_SERVIDOR, PUERTO_NET_TASK)

    cliente.sendto(b"Hola desde el cliente", servidor)
    print("Conectado al servidor.")
    
    data, _ = cliente.recvfrom(4096)
    with evento_lock:
        try:
            dato = pickle.loads(data)
        except pickle.UnpicklingError:
            print("Error al deserializar datos del servidor")
            return
    evento.set()

    while True:
        print("Esperando tareas...")
        perf, ping = False, False
        
        frequency = []
        with evento_lock:
            for task in dato.get('tasks', []):
                if task['name_report'] == 'ping':
                    ping = True
                if task['name_report'] == 'perf':
                    perf = True
                if task['frequency'] != None:
                    frequency.append(task['frequency'])
                else:
                    frequency.append(0)

        if perf:
            time.sleep(5)
            p = ejecutar_perf(IP_SERVIDOR)
            print(p)
            if p:
                cliente.sendto(b'guardar', servidor)
                cliente.sendto(b'IPERF', servidor)
                cliente.sendto(p.encode('utf-8'), servidor)
                ack= cliente.recv(BUFFER_SIZE)
                if ('ACK' !=  ack.decode()):
                    print("CLIENTE error no se recibio el ack")
                else :
                    print('CLIENTE ACK')
                w =  int(frequency[0].split()[0])
                print("Espera", w)

                time.sleep(w)
        if ping:
            nombre_archivo = "report_ping.txt"
            repo_ping = report_ping(nombre_archivo, IP_SERVIDOR)
            print(repo_ping)
            if repo_ping:
                cliente.sendto(b'guardar', servidor)
                cliente.sendto(b'PING', servidor)
                cliente.sendto(repo_ping.encode('utf-8'), servidor)
                ack = cliente.recv(BUFFER_SIZE)
                if ('ACK' !=  ack.decode()):
                    print("CLIENTE error no se recibio el ack")
                else :
                    print('CLIENETE ACK')
                
                # Texto del ping como string
                ping_output = "10 packets transmitted, 10 received, 0% packet loss, time 9199ms"
                # Buscar los números en la línea
                match = re.findall(r"(\d+) packets transmitted, (\d+) received", ping_output)
                if match:
                    match = re.search(r"(\d+)% packet loss", ping_output)
                    paquetes_perdidos = int(match.group(1)) if match else None
                    print("Paquetes perdidos:", paquetes_perdidos)  
                    cola.put(paquetes_perdidos)
                else:
                    print("No se encontraron datos en el ping.")
                    cola.put(SIN_DATO)


                w =  int(frequency[0].split()[0])
                print("Espera", w)

                time.sleep(w)
        

def enviar_alerta_tcp():
    time.sleep(2)
    tcp_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        tcp_socket.connect((IP_SERVIDOR, PUERTO_ALERT_FLOW))
        print("[ALERTA] Conexión establecida para alertas TCP.")
    except socket.error as e:
        print(f"Error al conectar con el servidor TCP: {e}")
        return

    evento.wait()
    with evento_lock:
        alertflow_conditions = dato.get("alertflow_conditions", {})
        cpu_percent_cond = int(alertflow_conditions.get('cpu_usage', '100%').strip('%')) / 100
        ram_percent_cond = int(alertflow_conditions.get('ram_usage', '100%').strip('%')) / 100
        packet_percent_cond = int(alertflow_conditions.get('packet_loss', '100%').strip('%')) / 100
    while True:
        cpu_percent = cpu_use()
        ram_percent = ram_use()
        packet_percent = cola.get()  # Obtiene dato de la cola

        if (packet_percent is not SIN_DATO):
           if  packet_percent_cond < packet_percent:
                alerta = 'Alerta: Condiciones de porentaje de paquetes superadas'
                print(f"[ALERTA] Enviando alerta: {alerta}")
                with tcp_lock:
                    tcp_socket.sendall(alerta.encode())

        if cpu_percent_cond < cpu_percent:
            alerta = 'Alerta: Condiciones de cpu superadas'
            print(f"[ALERTA] Enviando alerta: {alerta}")
            with tcp_lock:
                tcp_socket.sendall(alerta.encode())
        if ram_percent_cond < ram_percent:
            alerta = "Alerta: Condiciones de porcentaje de Ram superadas"
            print(f"[ALERTA] Enviando alerta: {alerta}")
            with tcp_lock:
                tcp_socket.sendall(alerta.encode())
        time.sleep(5)
    tcp_socket.close()

def report_ping(nombre_archivo, ip):
    try:
        result = subprocess.run(
            ["ping", "-c", "10", ip] if os.name != "nt" else ["ping", "-n", "10", ip],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        with archivo_lock:
            with open(nombre_archivo, "w") as archivo:
                archivo.write(result.stdout)
        return result.stdout
    except Exception as e:
        print(f"Error al generar el reporte de ping: {e}")
        return None

def ejecutar_perf(server_ip, port=5201):
    try:
        result = subprocess.run(["iperf3", "-c", server_ip, "-p", str(port)], capture_output=True, text=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        print(f"Error ejecutando iperf3: {e}")
        return None

def cpu_use():
    try:
        return psutil.cpu_percent(interval=3) / 100
    except Exception:
        return 1.0

def ram_use():
    try:
        return psutil.virtual_memory().percent / 100
    except Exception:
        return 1.0

if __name__ == "__main__":
    main()
