import sys
from mathbank.desktop import main
from mathbank.smoke import run

if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--smoke-test':
        raise SystemExit(run(sys.argv[2]))
    raise SystemExit(main())
