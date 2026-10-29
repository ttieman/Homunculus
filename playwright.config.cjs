module.exports = {
  testDir: './tests/browser',
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:8767', headless: true },
  webServer: { command: 'python server.py --port 8767 --no-clip', url: 'http://127.0.0.1:8767', reuseExistingServer: false,
    env: { HOMUNCULUS_CHARACTER: 'outputs/test-character.glb' } },
};
