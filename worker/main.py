import os
import sys
import argparse
import asyncio

# Reconfigure stdout and stderr to use UTF-8 to prevent Unicode crashes on Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
if sys.stderr.encoding != 'utf-8':
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass

# Thêm thư mục gốc vào path để có thể import từ worker.*
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker.application.planning_use_case import handle_planning
from worker.application.render_use_case import handle_render
from worker.application.publish_use_case import handle_publish


def record_job_failure(job_id: int, job_type: str, error: Exception) -> None:
    """Persist terminal worker failures so the operator can inspect and retry safely."""
    if job_type not in {"RENDER", "PUBLISH"}:
        return

    error_trace = f"{type(error).__name__}: {error}"[:2000]
    try:
        from worker.infrastructure.repositories import VideoJobRepository
        from worker.infrastructure.database import log_realtime_progress
        from worker.services.cockpit_bridge import update_task_progress

        VideoJobRepository().update_state(job_id, "FAILED", error_trace)
        log_realtime_progress(job_id, "WORKER_FAILURE", "ERROR", error_trace)
        update_task_progress(str(job_id), "FAILED", 0)
    except Exception as persistence_error:
        print(
            f"[Python Main Error] Could not persist failure for job #{job_id}: {persistence_error}",
            file=sys.stderr,
        )


def main():
    parser = argparse.ArgumentParser(description="Core Worker Python for Chat-Driven TikTok/YouTube Automation")
    parser.add_argument("--job-id", type=int, required=True, help="ID của bản ghi trong database")
    parser.add_argument("--type", type=str, required=True, choices=["PLANNING", "RENDER", "PUBLISH"], help="Loại tác vụ xử lý")
    parser.add_argument("--publish-target-id", type=int, required=False, help="ID của publish target cụ thể")
    parser.add_argument("--proxy-ip", type=str, required=False, default=None, help="Proxy IP address")
    parser.add_argument("--proxy-port", type=int, required=False, default=None, help="Proxy port number")
    parser.add_argument("--proxy-user", type=str, required=False, default=None, help="Proxy username")
    parser.add_argument("--proxy-pass", type=str, required=False, default=None, help="Proxy password")
    parser.add_argument("--lang-token", type=str, required=False, default=None, help="Localization language token")
    
    args = parser.parse_args()
    
    print(f"[Python Main] Running job #{args.job_id} of type {args.type}...")
    
    try:
        if args.type == "PLANNING":
            asyncio.run(handle_planning(args.job_id))
        elif args.type == "RENDER":
            asyncio.run(handle_render(args.job_id))
        elif args.type == "PUBLISH":
            handle_publish(
                args.job_id,
                args.publish_target_id,
                proxy_ip=args.proxy_ip,
                proxy_port=args.proxy_port,
                proxy_user=args.proxy_user,
                proxy_pass=args.proxy_pass,
                lang_token=args.lang_token
            )
        
        sys.exit(0)
        
    except Exception as e:
        record_job_failure(args.job_id, args.type, e)
        print(f"[Python Main Error] Process crashed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
