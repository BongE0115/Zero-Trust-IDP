import subprocess


def handle_cpu_recovery(event: dict):
    print("\n🔥 CPU Recovery 실행")
    print("→ Pod restart 시도")

    try:
        result = subprocess.run(
            ["kubectl", "rollout", "restart", "deployment", "my-app"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise Exception(result.stderr)

        print("✅ CPU Recovery 성공")

    except Exception as e:
        print(f"❌ CPU Recovery 실패: {e}")
        raise e


def handle_memory_recovery(event: dict):
    print("\n🔥 Memory Recovery 실행")
    print("→ Pod restart 시도")

    try:
        result = subprocess.run(
            ["kubectl", "rollout", "restart", "deployment", "my-app"],
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            raise Exception(result.stderr)

        print("✅ Memory Recovery 성공")

    except Exception as e:
        print(f"❌ Memory Recovery 실패: {e}")
        raise e