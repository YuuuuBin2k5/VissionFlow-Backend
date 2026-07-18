module.exports = {
  apps: [
    {
      name: 'agent-bot-orchestrator',
      cwd: './orchestrator',
      script: 'dist/main.js',
      exec_mode: 'fork',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '1200M',
      time: true,
      env: {
        NODE_ENV: 'production',
      },
    },
  ],
};
