output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}

output "api_key" {
  value     = random_password.api_key.result
  sensitive = true
}

output "iot_endpoint" {
  value = data.aws_iot_endpoint.data.endpoint_address
}

output "printer_credentials" {
  description = "PEM cert/key per printer. Read with scripts/export_credentials.py."
  sensitive   = true
  value = {
    for id, c in aws_iot_certificate.printer : id => {
      cert = c.certificate_pem
      key  = c.private_key
    }
  }
}
