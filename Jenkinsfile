pipeline {
    agent { label 'build-server' }

    environment {
        AWS_REGION = 'us-east-1' // Replace with your AWS region
        S3_BUCKET  = 'jenkins-ec2-inventory-reports' // Replace with your bucket name
        S3_FOLDER  = 'ec2-reports'
    }

    stages {
        stage('Collect EC2 Metadata & CloudWatch Metrics') {
            steps {
                sh '''
                    python3 - << 'EOF'
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

region = os.environ['AWS_REGION']
build_num = os.environ['BUILD_NUMBER']
now = datetime.now(timezone.utc)
start_time = (now - timedelta(hours=1)).strftime('%Y-%m-%dT%H:%M:%SZ')
end_time = now.strftime('%Y-%m-%dT%H:%M:%SZ')

metrics_list = [
    'CPUUtilization',
    'NetworkIn',
    'NetworkOut',
    'DiskReadBytes',
    'DiskWriteBytes',
    'StatusCheckFailed'
]

def run_aws(cmd):
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(result.stdout)

ec2_data = run_aws(['aws', 'ec2', 'describe-instances', '--region', region, '--output', 'json'])
report = {
    'GeneratedAtUTC': end_time,
    'Region': region,
    'Instances': []
}

for res in ec2_data.get('Reservations', []):
    for inst in res.get('Instances', []):
        inst_id = inst['InstanceId']
        tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
        state = inst.get('State', {}).get('Name')

        metrics_summary = {}
        if state == 'running':
            for metric in metrics_list:
                cw_data = run_aws([
                    'aws', 'cloudwatch', 'get-metric-statistics',
                    '--region', region,
                    '--namespace', 'AWS/EC2',
                    '--metric-name', metric,
                    '--dimensions', f'Name=InstanceId,Value={inst_id}',
                    '--start-time', start_time,
                    '--end-time', end_time,
                    '--period', '3600',
                    '--statistics', 'Average', 'Maximum',
                    '--output', 'json'
                ])
                datapoints = cw_data.get('Datapoints', [])
                if datapoints:
                    dp = datapoints[0]
                    metrics_summary[metric] = {
                        'Average': round(dp.get('Average', 0), 4),
                        'Maximum': round(dp.get('Maximum', 0), 4),
                        'Unit': dp.get('Unit')
                    }
                else:
                    metrics_summary[metric] = None

        report['Instances'].append({
            'InstanceId': inst_id,
            'Name': tags.get('Name'),
            'State': state,
            'InstanceType': inst.get('InstanceType'),
            'LaunchTime': inst.get('LaunchTime'),
            'PrivateIP': inst.get('PrivateIpAddress'),
            'PublicIP': inst.get('PublicIpAddress'),
            'AvailabilityZone': inst.get('Placement', {}).get('AvailabilityZone'),
            'MetricsLast1Hour': metrics_summary
        })

filename = f"ec2-report-{build_num}.json"
with open(filename, 'w') as f:
    json.dump(report, f, indent=2)

print(f"Saved report for {len(report['Instances'])} instances to {filename}")
EOF
                '''
            }
        }

        stage('Upload Report to S3') {
            steps {
                sh 'aws s3 cp ec2-report-${BUILD_NUMBER}.json s3://${S3_BUCKET}/${S3_FOLDER}/'
            }
        }
    }

    post {
        always {
            sh 'rm -f ec2-report-${BUILD_NUMBER}.json'
        }
    }
}
