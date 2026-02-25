module.exports = {
  apps: [
    {
      name: "ai-lead-agent",
      script: "main.py",
      interpreter: "python3",
      watch: false,
      autorestart: true,
      max_restarts: 10,
      restart_delay: 5000,
      env: {
        LOG_LEVEL: "INFO",
      },
      log_date_format: "YYYY-MM-DD HH:mm:ss",
      out_file: "logs/agent-out.log",
      error_file: "logs/agent-err.log",
    },
  ],
};
