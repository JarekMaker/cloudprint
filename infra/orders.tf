resource "aws_dynamodb_table" "orders" {
  name         = "${var.project}-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "job_id"

  attribute {
    name = "job_id"
    type = "S"
  }

  ttl {
    attribute_name = "expires"
    enabled        = true
  }
}

# Printed in the QR code of each kiosk; lets the public page order only for its own printer.
resource "random_password" "kiosk" {
  for_each = var.printers
  length   = 20
  special  = false
}
