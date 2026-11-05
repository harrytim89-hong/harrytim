import sys
from pathlib import Path
import os
import traceback

# -I isolates the portable interpreter; explicitly add only our installed source.
sys.path.insert(0, str(Path(__file__).resolve().parent))

if __name__ == '__main__':
    try:
        from mathbank.desktop import main
        from mathbank.smoke import run
        if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
            raise SystemExit(run(sys.argv[2]))
        raise SystemExit(main())
    except Exception:
        root = Path(os.environ.get('LOCALAPPDATA', Path.home()/'.local/share'))/'MathBankDesktop'
        root.mkdir(parents=True, exist_ok=True)
        (root/'startup-error.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise
