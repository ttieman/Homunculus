module.exports = {
  testDir: './tests/browser',
  workers: 1,
  // Two full-body retarget passes and project reloads can exceed the default UI timeout.
  timeout: 90000,
  expect: { timeout: 20000 },
  use: { baseURL: 'http://127.0.0.1:8767', headless: true },
  webServer: {
    // Test storage: browser tests must never touch the real private/ library.
    command: 'python server.py --port 8767 --no-clip --storage outputs/browser-test-storage',
    url: 'http://127.0.0.1:8767',
    reuseExistingServer: false,
    env: { HOMUNCULUS_CHARACTER: 'outputs/test-character.glb' },
  },
};
