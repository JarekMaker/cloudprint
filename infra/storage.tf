resource "random_id" "suffix" {
  byte_length = 4
}

resource "aws_s3_bucket" "jobs" {
  bucket        = "${var.project}-jobs-${random_id.suffix.hex}"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "jobs" {
  bucket                  = aws_s3_bucket.jobs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "jobs" {
  bucket = aws_s3_bucket.jobs.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# The kiosk page uploads straight from the browser with a presigned URL.
resource "aws_s3_bucket_cors_configuration" "jobs" {
  bucket = aws_s3_bucket.jobs.id

  cors_rule {
    allowed_methods = ["PUT"]
    allowed_origins = ["*"]
    allowed_headers = ["Content-Type"]
    max_age_seconds = 3000
  }
}

# Documents are sensitive and only needed until printed: delete after a day.
resource "aws_s3_bucket_lifecycle_configuration" "jobs" {
  bucket = aws_s3_bucket.jobs.id

  rule {
    id     = "expire-jobs"
    status = "Enabled"

    filter {
      prefix = "jobs/"
    }

    expiration {
      days = 1
    }
  }
}
