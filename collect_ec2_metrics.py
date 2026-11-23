#!/usr/bin/env python3
"""
Collects EC2 metadata and CloudWatch metrics for instances in a given AWS region
and saves the output to a JSON report using Boto3 (AWS SDK for Python).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone

import boto3
from botocore.exceptions import BotoCoreError, ClientError

METRICS_LIST = [
    'CPUUtilization',
    'NetworkIn',
    'NetworkOut',
    'EBSReadBytes',
    'EBSWriteBytes',
    'StatusCheckFailed'
]


def parse_arguments():
    parser = argparse.ArgumentParser(description="Collect EC2 metadata and CloudWatch metrics using Boto3.")
    parser.add_argument(
        '--region',
        default=os.environ.get('AWS_REGION', 'us-east-1'),
        help="AWS region (default: AWS_REGION env var or 'us-east-1')"
    )
    parser.add_argument(
        '--build-number',
        default=os.environ.get('JSON_BUILD_NUMBER') or os.environ.get('BUILD_NUMBER') or 'local',
        help="Jenkins JSON build number or identifier (default: JSON_BUILD_NUMBER / BUILD_NUMBER env var or 'local')"
    )
    parser.add_argument(
        '--output',
        default=None,
        help="Output JSON filename (default: ec2-report-python-<build_number>.json)"
    )
    return parser.parse_args()


def main():
    args = parse_arguments()
    region = args.region
    build_num = args.build_number
    output_filename = args.output or f"ec2-report-python-{build_num}.json"

    now = datetime.now(timezone.utc)
    start_time = now - timedelta(hours=1)
    end_time = now

    print(f"Querying EC2 instances in region: {region} via Boto3...")
    try:
        ec2 = boto3.client('ec2', region_name=region)
        cw = boto3.client('cloudwatch', region_name=region)
        paginator = ec2.get_paginator('describe_instances')
        page_iterator = paginator.paginate()
    except (ClientError, BotoCoreError) as err:
        print(f"Error initializing Boto3 client: {err}", file=sys.stderr)
        sys.exit(1)

    report = {
        'GeneratedAtUTC': end_time.strftime('%Y-%m-%dT%H:%M:%SZ'),
        'Region': region,
        'Instances': []
    }

    try:
        for page in page_iterator:
            for res in page.get('Reservations', []):
                for inst in res.get('Instances', []):
                    inst_id = inst['InstanceId']
                    tags = {t['Key']: t['Value'] for t in inst.get('Tags', [])}
                    state = inst.get('State', {}).get('Name')

                    metrics_summary = {}
                    if state == 'running':
                        for metric in METRICS_LIST:
                            try:
                                cw_data = cw.get_metric_statistics(
                                    Namespace='AWS/EC2',
                                    MetricName=metric,
                                    Dimensions=[{'Name': 'InstanceId', 'Value': inst_id}],
                                    StartTime=start_time,
                                    EndTime=end_time,
                                    Period=3600,
                                    Statistics=['Average', 'Maximum']
                                )
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
                            except (ClientError, BotoCoreError) as err:
                                print(f"Warning: Failed to fetch metric {metric} for instance {inst_id}: {err}", file=sys.stderr)
                                metrics_summary[metric] = None

                    launch_time = inst.get('LaunchTime')
                    launch_time_str = launch_time.isoformat() if hasattr(launch_time, 'isoformat') else (str(launch_time) if launch_time else None)

                    report['Instances'].append({
                        'InstanceId': inst_id,
                        'Name': tags.get('Name'),
                        'State': state,
                        'InstanceType': inst.get('InstanceType'),
                        'LaunchTime': launch_time_str,
                        'PrivateIP': inst.get('PrivateIpAddress'),
                        'PublicIP': inst.get('PublicIpAddress'),
                        'AvailabilityZone': inst.get('Placement', {}).get('AvailabilityZone'),
                        'MetricsLast1Hour': metrics_summary
                    })
    except (ClientError, BotoCoreError) as err:
        print(f"Error querying EC2 via Boto3: {err}", file=sys.stderr)
        sys.exit(1)

    with open(output_filename, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Successfully saved report for {len(report['Instances'])} instances to {output_filename}")


if __name__ == '__main__':
    main()
