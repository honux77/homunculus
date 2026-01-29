import os
import time
import multiprocessing
import threading
from flask import Flask, render_template, jsonify
import psutil
import urllib.request
import urllib.error

app = Flask(__name__)

# CPU 부하 생성 상태 관리
stress_active = False
stress_end_time = 0
stress_processes = []


def get_instance_id():
    """AWS EC2 인스턴스 ID를 가져옴"""
    try:
        # IMDSv2 토큰 획득
        token_request = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "21600"},
            method="PUT"
        )
        with urllib.request.urlopen(token_request, timeout=2) as response:
            token = response.read().decode()

        # 토큰으로 instance-id 조회
        id_request = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/instance-id",
            headers={"X-aws-ec2-metadata-token": token}
        )
        with urllib.request.urlopen(id_request, timeout=2) as response:
            return response.read().decode()
    except Exception:
        # EC2가 아닌 환경에서는 hostname 반환
        return f"local-{os.uname().nodename}"


def cpu_stress_worker(stop_event):
    """CPU 부하를 생성하는 워커 함수 (90% 목표)"""
    while not stop_event.is_set():
        # 90% 사용률을 위해 90ms 작업, 10ms 휴식
        start = time.time()
        while time.time() - start < 0.09:
            _ = sum(i * i for i in range(1000))
        time.sleep(0.01)


def start_stress():
    """모든 CPU 코어에 부하 생성 시작"""
    global stress_active, stress_end_time, stress_processes

    if stress_active:
        return False

    stress_active = True
    stress_end_time = time.time() + 300  # 5분

    cpu_count = multiprocessing.cpu_count()
    stop_event = multiprocessing.Event()

    for _ in range(cpu_count):
        p = multiprocessing.Process(target=cpu_stress_worker, args=(stop_event,))
        p.start()
        stress_processes.append((p, stop_event))

    # 5분 후 자동 종료를 위한 타이머
    def auto_stop():
        time.sleep(300)
        stop_stress()

    threading.Thread(target=auto_stop, daemon=True).start()
    return True


def stop_stress():
    """CPU 부하 생성 중지"""
    global stress_active, stress_processes

    for p, stop_event in stress_processes:
        stop_event.set()
        p.terminate()
        p.join(timeout=1)

    stress_processes = []
    stress_active = False


@app.route("/")
def index():
    instance_id = get_instance_id()
    return render_template("index.html", instance_id=instance_id)


@app.route("/api/cpu")
def get_cpu():
    """현재 CPU 사용률 반환"""
    cpu_percent = psutil.cpu_percent(interval=0.5)
    cpu_per_core = psutil.cpu_percent(interval=0, percpu=True)

    remaining = 0
    if stress_active:
        remaining = max(0, int(stress_end_time - time.time()))

    return jsonify({
        "cpu_percent": cpu_percent,
        "cpu_per_core": cpu_per_core,
        "stress_active": stress_active,
        "remaining_seconds": remaining
    })


@app.route("/api/stress/start", methods=["POST"])
def api_start_stress():
    """CPU 부하 생성 시작"""
    success = start_stress()
    return jsonify({"success": success, "message": "Stress test started" if success else "Already running"})


@app.route("/api/stress/stop", methods=["POST"])
def api_stop_stress():
    """CPU 부하 생성 중지"""
    stop_stress()
    return jsonify({"success": True, "message": "Stress test stopped"})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
