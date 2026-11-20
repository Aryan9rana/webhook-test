pipeline {
    agent { label 'build-server' }

    environment {
        AWS_REGION = 'us-east-1'
        S3_BUCKET  = 'jenkins-ec2-inventory-reports'
        S3_FOLDER  = 'ec2-reports'
    }

    stages {
        stage('Collect EC2 Metadata & CloudWatch Metrics') {
            steps {
                sh 'python3 collect_ec2_metrics.py --region ${AWS_REGION} --build-number ${BUILD_NUMBER}'
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
