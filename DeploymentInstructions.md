Deployment Instructions
Initial Setup
Clone and configure:
git clone https://github.com/YOUR_USERNAME/bigquery-cost-monitoring.git
cd bigquery-cost-monitoring
cp terraform/terraform.tfvars.example terraform/terraform.tfvars
# Edit terraform.tfvars
Deploy infrastructure:
cd terraform
terraform init
terraform apply
Update Cloud Build trigger:
Edit terraform/main.tf and update the GitHub owner/repo in google_cloudbuild_trigger.deploy_trigger

Connect GitHub repository:

# In GCP Console, connect your GitHub repo to Cloud Build
# Or use: gcloud beta builds triggers create github ...
Initial Cloud Run deployment:
cd ..
gcloud builds submit --config cloudbuild.yaml
Continuous Deployment
After initial setup, every push to main branch automatically deploys via Cloud Build.