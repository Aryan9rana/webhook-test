pipeline {
    agent { label 'build-server' }

    environment {
        AWS_REGION       = 'us-east-1'
        S3_BUCKET        = 'jenkins-ec2-inventory-reports'
        S3_FOLDER        = 'ec2-reports'
        CSV_BUILD_NUMBER = "${BUILD_NUMBER}"
    }

    stages {
        stage('Collect EC2 Metadata & CloudWatch Metrics via Ansible (CSV)') {
            steps {
                sh '''
                    ansible-playbook collect_ec2_metrics_csv.yml \
                        -e aws_region=${AWS_REGION} \
                        -e csv_build_number=${CSV_BUILD_NUMBER}
                '''
            }
        }

        stage('Upload CSV Report to S3') {
            steps {
                sh 'aws s3 cp ec2-report-ansible-${CSV_BUILD_NUMBER}.csv s3://${S3_BUCKET}/${S3_FOLDER}/'
            }
        }
    }

    post {
        always {
            sh 'rm -f ec2-report-ansible-${CSV_BUILD_NUMBER}.csv'
        }
    }
}
