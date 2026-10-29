"""Start the Homunculus editor: python server.py [--port 8765] [--clip DIR] [--character GLB] [--worker URL]

The code lives in homunculus/ (see docs/ARCHITECTURE.md); this file is only the launcher.
"""

from homunculus.editor.server import main

if __name__ == '__main__':
    main()
