import { http } from "@/shared/lib/http";
import { EmailValidationSchema } from "@/entities/emailValidation/schema";
import { ApiError } from "@/shared/lib/errors";

export async function fetchLatestEmailValidation(window: "daily" | "weekly") {
  try {
    return EmailValidationSchema.parse(await http.get("/email-validation/latest", { window }));
  } catch (error) {
    // No run exists yet for this window; render empty-state instead of hard failure.
    if (error instanceof ApiError && error.status === 404) {
      return EmailValidationSchema.parse({ item: null });
    }
    throw error;
  }
}

export async function runEmailValidation(window: "daily" | "weekly") {
  return await http.post<{ accepted: boolean; status?: string }>("/admin/email-validation/run", undefined, {
    window,
    force: true,
  });
}
