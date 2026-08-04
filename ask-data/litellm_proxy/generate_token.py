import json
import subprocess
import sys


def get_cdp_token(
    workload_name: str = "DE",
    endpoint_url: str = "https://console-cdp.apps.dataservices.bni.co.id",
) -> str:
    """
    Executes 'cdp iam generate-workload-auth-token' with internal BNI CML parameters
    and returns a fresh JWT token string.
    """
    cmd = [
        "cdp",
        "iam",
        "generate-workload-auth-token",
        "--workload-name",
        workload_name,
        "--no-verify-tls",
        "--endpoint-url",
        endpoint_url,
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        payload = json.loads(result.stdout)
        token = payload.get("token", "")
        return token

    except FileNotFoundError:
        print("❌ Error: 'cdp' command not found in system PATH.", file=sys.stderr)
        print("💡 Install the CDP CLI via: pip install cdpcli", file=sys.stderr)
        return ""
    except subprocess.CalledProcessError as e:
        print(f"❌ CLI Error: {e.stderr.strip()}", file=sys.stderr)
        return ""
    except json.JSONDecodeError:
        print("❌ Failed to parse JSON from CDP CLI output.", file=sys.stderr)
        return ""
    except Exception as e:
        print(f"❌ Unexpected error fetching CDP token: {e}", file=sys.stderr)
        return ""


if __name__ == "__main__":
    cdp_token = get_cdp_token()
    if cdp_token:
        print(f"CDP_TOKEN={cdp_token}")