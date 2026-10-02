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

output "kiosk_queries" {
  description = "Query string for each kiosk page link, e.g. https://<pages-url>/?p=office-1&t=..."
  sensitive   = true
  value       = { for id, p in random_password.kiosk : id => "p=${id}&t=${p.result}" }
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
