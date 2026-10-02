data "aws_iot_endpoint" "data" {
  endpoint_type = "iot:Data-ATS"
}

resource "aws_iot_thing" "printer" {
  for_each = var.printers
  name     = each.key
}

resource "aws_iot_certificate" "printer" {
  for_each = var.printers
  active   = true
}

# One policy for all printers. Policy variables pin each device to its own client id and topics,
# so a stolen certificate cannot read or write another printer's channel.
resource "aws_iot_policy" "printer" {
  name = "${var.project}-printer"

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "iot:Connect"
        Resource = "arn:aws:iot:${var.region}:${data.aws_caller_identity.current.account_id}:client/$${iot:Connection.Thing.ThingName}"
      },
      {
        Effect   = "Allow"
        Action   = "iot:Subscribe"
        Resource = "arn:aws:iot:${var.region}:${data.aws_caller_identity.current.account_id}:topicfilter/printers/$${iot:Connection.Thing.ThingName}/jobs"
      },
      {
        Effect   = "Allow"
        Action   = "iot:Receive"
        Resource = "arn:aws:iot:${var.region}:${data.aws_caller_identity.current.account_id}:topic/printers/$${iot:Connection.Thing.ThingName}/jobs"
      },
      {
        Effect   = "Allow"
        Action   = ["iot:Publish", "iot:RetainPublish"]
        Resource = "arn:aws:iot:${var.region}:${data.aws_caller_identity.current.account_id}:topic/printers/$${iot:Connection.Thing.ThingName}/status"
      },
    ]
  })
}

resource "aws_iot_policy_attachment" "printer" {
  for_each = var.printers
  policy   = aws_iot_policy.printer.name
  target   = aws_iot_certificate.printer[each.key].arn
}

resource "aws_iot_thing_principal_attachment" "printer" {
  for_each  = var.printers
  thing     = aws_iot_thing.printer[each.key].name
  principal = aws_iot_certificate.printer[each.key].arn
}
