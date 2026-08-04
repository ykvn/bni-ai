import subprocess
import json
import sys

def get_cdp_token(workload_name: str = "DE") -> str:
    """
    Executes 'cdp iam generate-workload-auth-token' and returns the token string.
    """
    cmd = ["cdp", "iam", "generate-workload-auth-token", "--workload-name", workload_name]
    
    try:
        # Run CLI command and capture output
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        
        # Parse JSON output (replaces jq)
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

if __name__ == "__main__":
    cdp_token = get_cdp_token()
    if cdp_token:
        print(f"CDP_TOKEN={cdp_token}")