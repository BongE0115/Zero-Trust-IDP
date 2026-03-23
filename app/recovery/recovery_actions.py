import os


def handle_cpu_recovery(event: dict):
    print("\n🔥 CPU Recovery 실행")
    print("→ Docker 컨테이너 재시작 시도")

    os.system("echo 'docker restart my-app-container'")

    print("→ Recovery 명령 실행 완료")


def handle_memory_recovery(event: dict):
    print("\n🔥 Memory Recovery 실행")
    print("→ 메모리 정리 또는 재시작 예정")

    os.system("echo 'memory cleanup or restart'")

    print("→ Recovery 명령 실행 완료")