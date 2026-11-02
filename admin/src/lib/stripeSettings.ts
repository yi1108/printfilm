type StripeSettings = {
  stripe_enabled: boolean;
  stripe_frontend_url: string;
  public_base_url?: string;
  has_stripe_secret_key: boolean;
  has_stripe_webhook_secret: boolean;
  stripe_currency?: string;
  stripe_usd_cny_rate?: string;
};

export type StripeSecretDrafts = {
  secretKey: string;
  webhookSecret: string;
  clearSecretKey: boolean;
  clearWebhookSecret: boolean;
};

/** Blank drafts preserve saved secrets; explicit clears take precedence over a draft. */
export function stripeSettingsPatch(settings: StripeSettings, drafts: StripeSecretDrafts) {
  return {
    stripe_enabled: Boolean(settings.stripe_enabled),
    stripe_frontend_url: (settings.stripe_frontend_url || "").trim(),
    stripe_currency: "auto",
    stripe_usd_cny_rate: (settings.stripe_usd_cny_rate || "").trim(),
    stripe_secret_key: drafts.clearSecretKey ? undefined : drafts.secretKey.trim() || undefined,
    clear_stripe_secret_key: drafts.clearSecretKey,
    stripe_webhook_secret: drafts.clearWebhookSecret ? undefined : drafts.webhookSecret.trim() || undefined,
    clear_stripe_webhook_secret: drafts.clearWebhookSecret,
  };
}

export function stripeSettingsReady(settings: StripeSettings, drafts: StripeSecretDrafts): boolean {
  const hasKey = !drafts.clearSecretKey && (settings.has_stripe_secret_key || Boolean(drafts.secretKey.trim()));
  const hasWebhook = !drafts.clearWebhookSecret && (settings.has_stripe_webhook_secret || Boolean(drafts.webhookSecret.trim()));
  const returnSite = settings.stripe_frontend_url?.trim() || settings.public_base_url?.trim();
  const rate = settings.stripe_usd_cny_rate;
  const rateReady = Boolean(rate?.trim() && !stripeRateInputError(rate));
  return Boolean(settings.stripe_enabled && returnSite && hasKey && hasWebhook && rateReady);
}

/** Keep the original decimal text; rate validation must never round a draft through a float. */
export function stripeRateInputError(value: string | undefined): string | undefined {
  const raw = (value || "").trim();
  if (!raw) return undefined;
  if (!/^\d+(?:\.\d{1,6})?$/.test(raw)) return "请输入最多六位小数的正数汇率。";
  const amount = Number(raw);
  if (!Number.isFinite(amount) || amount <= 0 || amount > 1_000_000) return "汇率须大于 0 且不超过 1000000。";
  return undefined;
}
