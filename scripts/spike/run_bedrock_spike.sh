#!/usr/bin/env bash
# Task 1.5 wrapper: reports credential presence (never values), then runs the spike.
echo "region_env=${AWS_REGION:-${AWS_DEFAULT_REGION:-unset}} profile=${AWS_PROFILE:-unset}"
echo "access_key_env=$([ -n "$AWS_ACCESS_KEY_ID" ] && echo set || echo unset)"
echo "bearer_env=$([ -n "$AWS_BEARER_TOKEN_BEDROCK" ] && echo set || echo unset)"
echo "aws_credentials_file=$([ -f ~/.aws/credentials ] && echo yes || echo no)"
echo "aws_config_file=$([ -f ~/.aws/config ] && echo yes || echo no)"
timeout 100 uv run --with strands-agents --with botocore[crt] python scripts/spike/bedrock_spike.py 2>&1 | tail -5
