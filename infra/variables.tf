variable "region" {
  type    = string
  default = "eu-central-1"
}

variable "project" {
  type    = string
  default = "cloudprint"
}

variable "printers" {
  description = "Printer IDs. Each gets its own IoT thing and certificate."
  type        = set(string)
  default     = ["office-1"]

  validation {
    condition     = alltrue([for p in var.printers : can(regex("^[A-Za-z0-9_-]{1,40}$", p))])
    error_message = "Printer IDs may only contain letters, digits, '-' and '_' (max 40 chars)."
  }
}
