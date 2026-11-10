/** 由供应方法务 HTML 转换的结构化正文；渲染时不注入原始 HTML。 */
export type LegalBlock =
  | { type: 'paragraph'; text: string }
  | { type: 'bullets'; items: string[] }

export type LegalSection = {
  title: string
  blocks: LegalBlock[]
}

export type LegalDocument = {
  slug: 'terms' | 'privacy'
  title: string
  updatedAt: string
  intro: string[]
  sections: LegalSection[]
}

export const LEGAL_DOCS: Record<'terms' | 'privacy', LegalDocument> = {
  "terms": {
    "slug": "terms",
    "title": "Terms of Use",
    "updatedAt": "November 9, 2026",
    "intro": [
      "These Terms of Use (“Terms”) are a contract between you and Shenzhen Depei Open Source Data Technology Co., Ltd. (“PrintFilm,” “we,” “us,” or “our”). They govern your access to and use of the PrintFilm mobile application, the website at [https://www.printfilm.com](https://www.printfilm.com), and related generation, playback, and account services (together, the “Service”).",
      "By creating an account, tapping agree, purchasing credits or Studio access, or otherwise using the Service, you agree to these Terms and to our [Privacy Policy](/privacy). If you do not agree, do not use the Service."
    ],
    "sections": [
      {
        "title": "1. The Service",
        "blocks": [
          {
            "type": "paragraph",
            "text": "PrintFilm lets you watch short films and create images and videos from prompts. Depending on the feature, the Service includes:"
          },
          {
            "type": "bullets",
            "items": [
              "A Watch feed of short videos, including free, preview, and credit-unlocked titles;",
              "Cloud generation of images and videos from text you submit, and from photos you choose to upload;",
              "On-device Studio tools, including Assistant, Voice, and Music, after a separate one-time purchase;",
              "A PrintFilm account, credit balance, usage history, and purchased-video library;",
              "Comments, likes, shares, and other community features where we enable them."
            ]
          },
          {
            "type": "paragraph",
            "text": "Some features are available without an account. Creating, buying credits, unlocking paid videos, commenting, and editing your profile require an email account. We may add, change, or withdraw features, and availability can differ by country, device, and app version."
          }
        ]
      },
      {
        "title": "2. Eligibility",
        "blocks": [
          {
            "type": "paragraph",
            "text": "You must be at least 13 years old, or the higher minimum age required where you live, to use PrintFilm. If you are under 18, you may use the Service only with the consent of a parent or legal guardian, and that person is responsible for your use. The Service is not directed to children under 13."
          }
        ]
      },
      {
        "title": "3. Accounts",
        "blocks": [
          {
            "type": "paragraph",
            "text": "You register with an email address and password and choose a display name. You may also add an optional phone number and profile photo. You are responsible for keeping your credentials confidential and for activity under your account. Tell us promptly at [support@printfilm.com](mailto:support@printfilm.com) if you believe your account is compromised."
          },
          {
            "type": "paragraph",
            "text": "You may browse limited parts of Watch as a guest. Guest use does not create a credit balance or a purchased-video library. Credits, generation history, and unlocks stay with the PrintFilm account that acquired them."
          },
          {
            "type": "paragraph",
            "text": "We may refuse a registration, reclaim a display name, or suspend an account that is unused, misleading, or in breach of these Terms."
          }
        ]
      },
      {
        "title": "4. Apple App Store",
        "blocks": [
          {
            "type": "paragraph",
            "text": "If you downloaded PrintFilm from Apple’s App Store, these additional terms apply:"
          },
          {
            "type": "bullets",
            "items": [
              "These Terms are between you and PrintFilm only, not with Apple Inc. (“Apple”). Apple is not responsible for the Service or its content.",
              "Your use of the app must also comply with the App Store terms and the Usage Rules in the Apple Media Services terms.",
              "Apple has no obligation to provide maintenance or support for the app. Support requests should be sent to [support@printfilm.com](mailto:support@printfilm.com).",
              "If the app fails to conform to an applicable warranty, you may notify Apple, and Apple may refund the purchase price of the app itself, if any. To the maximum extent permitted by law, Apple has no other warranty obligation for the app. Any other claim, loss, or liability relating to the app is PrintFilm’s responsibility, subject to these Terms.",
              "Apple is not responsible for claims relating to the app or your possession or use of it, including product-liability claims, claims that the app fails to meet a legal requirement, and consumer-protection or privacy claims.",
              "If a third party claims that the app or your use of it infringes that party’s intellectual-property rights, PrintFilm, not Apple, is responsible for the investigation, defense, settlement, and discharge of that claim, to the extent required by Apple’s terms.",
              "You represent that you are not located in a country subject to a U.S. Government embargo or designated as a “terrorist supporting” country, and that you are not listed on any U.S. Government list of prohibited or restricted parties.",
              "Apple and Apple’s subsidiaries are third-party beneficiaries of this section and may enforce it against you."
            ]
          },
          {
            "type": "paragraph",
            "text": "In-app digital goods are sold through Apple In-App Purchase. Apple’s payment sheet shows the price and currency before you confirm. We do not ask you to pay for credits, Studio access, or other digital items inside the iOS app by any method other than Apple In-App Purchase."
          }
        ]
      },
      {
        "title": "5. Credits",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Cloud generation and paid Watch titles use PrintFilm credits held in your account."
          },
          {
            "type": "bullets",
            "items": [
              "Credit packs are consumable in-app purchases. The price is the price displayed by Apple at checkout.",
              "Credits do not expire and have no cash value. They are not a bank balance, deposit, or e-money, and they cannot be redeemed for cash or transferred to another person, except where we expressly agree in writing, for example an enterprise arrangement requested through support.",
              "A completed credit purchase is added to the PrintFilm account that was signed in at checkout. Sign in to that same account to see the balance and purchase history. Using Restore Purchases does not grant those credits a second time.",
              "When generation starts, we may place a hold based on an estimate and then settle the charge from actual use, including tokens processed for the request. Image generation and video generation can cost different amounts. The usage screen shows the record we have for your account.",
              "If Apple approves a refund, we may reverse unused credits from that purchase and adjust related access. Credits already spent on a completed generation or unlock are not restored unless we are required to do so.",
              "The same account balance may be available on the PrintFilm website. Credits bought outside the iOS app, where that is offered, can be used in the app. Inside the iOS app, you buy credits only through Apple."
            ]
          },
          {
            "type": "paragraph",
            "text": "Buying credits does not guarantee that an AI result will match your prompt, be error-free, or be suitable for a particular purpose."
          }
        ]
      },
      {
        "title": "6. Studio access",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Assistant, Voice, and Music are on-device Studio tools. They are unlocked by a separate one-time, non-consumable in-app purchase, not by credits and not by a subscription. Other Studio entries may open without that purchase. Cloud generation still uses credits."
          },
          {
            "type": "paragraph",
            "text": "You can restore Studio access on a device signed in with the same Apple ID by using Restore Purchase. If Apple revokes or refunds that purchase, we may lock those tools again. Studio features that run on the device can request access to the microphone, speech recognition, photos, contacts, calendars, reminders, or location only when you ask the tool to use them."
          }
        ]
      },
      {
        "title": "7. Paid videos",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Some Watch titles can be previewed and then unlocked with credits. The app shows the credit price before you confirm. An unlock is for the published version you purchased and is tied to your PrintFilm account. It is not a transfer of copyright in the film. If a title is removed, restricted, or no longer playable, we may provide the access our playback rules allow for that purchased version, or the remedy required by law. Unlocking spends credits and is separate from buying a credit pack."
          }
        ]
      },
      {
        "title": "8. Acceptable use",
        "blocks": [
          {
            "type": "paragraph",
            "text": "You agree not to:"
          },
          {
            "type": "bullets",
            "items": [
              "Break the law, or infringe anyone’s intellectual property, privacy, or other rights;",
              "Upload, generate, publish, or share content that is illegal, exploitative of minors, non-consensual sexual content, harassing, hateful, or that threatens violence;",
              "Attempt to create sexual content involving anyone under 18, or any content that sexualizes minors;",
              "Impersonate another person, run a scam, or send spam;",
              "Probe, scrape, overload, reverse engineer, or bypass the Service, safety filters, generation limits, paywalls, or access controls, except where a law expressly allows that activity;",
              "Use the Service to develop competing models by systematically extracting outputs, or to train a model on our service outputs without permission;",
              "Misrepresent AI output as a factual recording of a real event or as a real person’s unaltered likeness, where that would deceive someone;",
              "Interfere with other people’s use of the Service or with our moderation."
            ]
          },
          {
            "type": "paragraph",
            "text": "We have zero tolerance for objectionable content and abusive behavior on the Service. We may remove content, refuse generation, limit features, or suspend or close an account, without refund of spent credits, when we believe these Terms have been broken."
          }
        ]
      },
      {
        "title": "9. Your content and AI output",
        "blocks": [
          {
            "type": "paragraph",
            "text": "You keep ownership of the prompts, photos, comments, and other materials you submit (“Your Content”), subject to rights others already have in those materials. You grant PrintFilm a worldwide, non-exclusive license to host, reproduce, process, display, and distribute Your Content and the outputs created from it only as needed to operate, secure, moderate, and improve the Service, and to show content you choose to publish in Watch or comments."
          },
          {
            "type": "paragraph",
            "text": "You represent that you have the rights needed to submit Your Content, including any photo of a person or any reference image, and that your use of outputs will comply with the law."
          },
          {
            "type": "paragraph",
            "text": "Images and videos produced by the Service are generated by automated systems. They may be inaccurate, incomplete, similar to other people’s outputs, or unexpected. You are responsible for reviewing outputs before you rely on them, publish them, or export them. Do not treat an output as professional, medical, legal, or financial advice, or as a depiction of a real event, unless you have verified it yourself."
          },
          {
            "type": "paragraph",
            "text": "We may use safety filters and human or automated review. We do not promise that filters will catch every prompt or output. We may refuse or delete a generation or post that breaches these Terms."
          }
        ]
      },
      {
        "title": "10. Watch, comments, and moderation",
        "blocks": [
          {
            "type": "paragraph",
            "text": "If you publish, comment, like, or share, you must follow these Terms. Other users’ content is theirs or their licensors’, not ours. We do not undertake to monitor everything, but we provide tools to flag a video and to block or mute a creator, and we review reports."
          },
          {
            "type": "paragraph",
            "text": "When we receive a report of content that violates these Terms, we will act on it within 24 hours where the report gives us enough information to identify the content, including by removing the content and restricting the account of a user who posted it. You can also email [support@printfilm.com](mailto:support@printfilm.com)."
          }
        ]
      },
      {
        "title": "11. Intellectual property",
        "blocks": [
          {
            "type": "paragraph",
            "text": "PrintFilm, the app, the website, our name and logo, and the software and design of the Service are owned by us or our licensors. These Terms do not give you any right to use our branding, except to identify the Service truthfully. You may not copy the Service or bypass technical limits."
          },
          {
            "type": "paragraph",
            "text": "If you believe content on the Service infringes your copyright, email [support@printfilm.com](mailto:support@printfilm.com) with: your name and contact details; a description of the work; the URL or in-app location of the material; a statement that you have a good-faith belief the use is not authorized; and a statement, under penalty of perjury where applicable, that the information is accurate and that you are the owner or the owner’s agent. We may remove the material and, where appropriate, notify the account holder."
          }
        ]
      },
      {
        "title": "12. Privacy",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Our [Privacy Policy](/privacy) explains what we collect and how we use it. You can close your account in the app at Me → Settings → Close Account. Closure is meant to be permanent and removes the profile and associated personal data, subject to the retention described in the Privacy Policy."
          }
        ]
      },
      {
        "title": "13. Disclaimers",
        "blocks": [
          {
            "type": "paragraph",
            "text": "The Service, including AI outputs, playback, and credits, is provided “as is” and “as available.” To the maximum extent permitted by law, we disclaim warranties of merchantability, fitness for a particular purpose, title, non-infringement, and uninterrupted or error-free operation. We do not warrant that generation will be available at all times, that a given prompt will succeed, or that outputs will be unique or accurate."
          },
          {
            "type": "paragraph",
            "text": "Nothing in these Terms excludes a warranty, right, or remedy that cannot legally be excluded, including statutory consumer guarantees in your country of residence."
          }
        ]
      },
      {
        "title": "14. Limitation of liability",
        "blocks": [
          {
            "type": "paragraph",
            "text": "To the maximum extent permitted by law, PrintFilm and its directors, employees, and suppliers will not be liable for indirect, incidental, special, consequential, or punitive damages, or for loss of profits, data, goodwill, or content, arising out of the Service or these Terms."
          },
          {
            "type": "paragraph",
            "text": "Our total liability for all claims relating to the Service in any 12-month period is limited to the greater of the amount you paid us for the Service during those 12 months or 50 U.S. dollars, except where a law does not allow that limit."
          },
          {
            "type": "paragraph",
            "text": "We are not liable for the acts of other users, for Apple’s payment processing, or for your decision to publish or rely on an AI output."
          }
        ]
      },
      {
        "title": "15. Indemnity",
        "blocks": [
          {
            "type": "paragraph",
            "text": "You will indemnify and hold PrintFilm harmless from claims, damages, and reasonable legal fees arising out of Your Content, your use of outputs, or your breach of these Terms, except to the extent caused by our own breach or unlawful conduct, and except where the law does not allow this indemnity."
          }
        ]
      },
      {
        "title": "16. Suspension and ending access",
        "blocks": [
          {
            "type": "paragraph",
            "text": "You may stop using the Service at any time and may close your account in the app. We may suspend or end access, or stop offering the Service, if you breach these Terms, if we must do so for safety or legal reasons, or if we discontinue a feature. Where the law requires notice, we will give it. Sections that by their nature should survive, including licenses already granted for operated content, acceptable-use limits, disclaimers, liability limits, and governing law, will survive."
          }
        ]
      },
      {
        "title": "17. Changes",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We may update these Terms. We will change the “Last updated” date and post the new Terms at [https://www.printfilm.com/terms](/terms). If a change is material, we will also provide a notice in the app or by email where that is reasonable. Continued use after the update takes effect means you accept the updated Terms. If you do not agree, stop using the Service and close your account."
          }
        ]
      },
      {
        "title": "18. Governing law",
        "blocks": [
          {
            "type": "paragraph",
            "text": "These Terms are governed by the laws of the People’s Republic of China, without regard to conflict-of-law rules. Subject to the next paragraph, the courts located in Shenzhen, Guangdong, China, have exclusive jurisdiction."
          },
          {
            "type": "paragraph",
            "text": "If you live in a country whose consumer laws give you mandatory rights or the right to bring a claim in your local courts, those rights are not reduced by this section. Consumers in the European Economic Area, the United Kingdom, and Switzerland may also bring proceedings in the courts of their place of residence."
          }
        ]
      },
      {
        "title": "19. Other terms",
        "blocks": [
          {
            "type": "paragraph",
            "text": "If a provision of these Terms is unenforceable, the rest remains in effect. A failure to enforce a provision is not a waiver. You may not assign these Terms without our consent. We may assign them as part of a reorganization, financing, or sale of the Service. These Terms, together with the Privacy Policy and the in-app purchase disclosures presented at checkout, are the entire agreement between you and us about the Service."
          }
        ]
      },
      {
        "title": "20. Contact",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Shenzhen Depei Open Source Data Technology Co., Ltd.\nEmail: [support@printfilm.com](mailto:support@printfilm.com)\nWebsite: [https://www.printfilm.com](https://www.printfilm.com)\nSupport: [https://www.printfilm.com/support](https://www.printfilm.com/support)"
          }
        ]
      }
    ]
  },
  "privacy": {
    "slug": "privacy",
    "title": "Privacy Policy",
    "updatedAt": "November 9, 2026",
    "intro": [
      "Shenzhen Depei Open Source Data Technology Co., Ltd. (“PrintFilm,” “we,” “us,” or “our”) respects your privacy. This policy explains how we collect, use, and share information when you use the PrintFilm iOS app, [https://www.printfilm.com](https://www.printfilm.com), and related generation, playback, and account services (the “Service”).",
      "If you do not agree with this policy, do not use the Service. Our [Terms of Use](/terms) explain the rules for using PrintFilm."
    ],
    "sections": [
      {
        "title": "1. Who is responsible",
        "blocks": [
          {
            "type": "paragraph",
            "text": "The controller of your personal information is Shenzhen Depei Open Source Data Technology Co., Ltd. You can contact us at [support@printfilm.com](mailto:support@printfilm.com)."
          }
        ]
      },
      {
        "title": "2. Information we collect",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We collect the following categories of information, depending on how you use the Service."
          },
          {
            "type": "paragraph",
            "text": "**Account information.** When you register or sign in, we collect your email address, password (stored by us only in a protected form), and display name. If you add them, we also collect an optional phone number and a profile photo. We keep an account identifier so we can associate your credits, generations, and purchases with you."
          },
          {
            "type": "paragraph",
            "text": "**Guest identifier.** If you use Watch or sharing without an account, the app creates a random identifier on the device and may send it with a share event so we can count that share. It is not used to track you across other companies’ apps or websites."
          },
          {
            "type": "paragraph",
            "text": "**Content you submit.** We collect text prompts, photos or reference images you choose to upload, comments, captions, likes, reports, and videos or images you ask us to generate or publish. If you save a result to Photos, that copy stays on your device under your control."
          },
          {
            "type": "paragraph",
            "text": "**Voice.** If you dictate a prompt or use a voice feature, speech is converted to text on your device with Apple’s speech recognition. We receive the resulting text if you submit it as a prompt or message. We do not receive a recording from that on-device transcription unless a feature you start clearly sends audio to us."
          },
          {
            "type": "paragraph",
            "text": "**On-device Studio data.** After you unlock Studio, Assistant, Voice, and Music run on your iPhone. If you ask the assistant to use them, the app may access your microphone, photos, contacts, calendars, reminders, or location. Those permissions are requested by iOS for that action. We do not upload your contacts, calendar, or reminders merely because the permission exists."
          },
          {
            "type": "paragraph",
            "text": "**Purchases and usage.** We receive records of credit packs and the Studio unlock so we can deliver what you bought. Apple processes the payment. We do not receive your full payment-card number. We keep credit balance, holds, generation charges, token usage, unlocks of paid videos, and purchase history for the account."
          },
          {
            "type": "paragraph",
            "text": "**Device and log data.** We collect device model, operating-system version, app version, language, IP address, and timestamps. We use this to deliver the Service, keep accounts signed in, prevent abuse, and diagnose failures."
          },
          {
            "type": "paragraph",
            "text": "**Support messages.** If you email [support@printfilm.com](mailto:support@printfilm.com), we keep the message and the contact details you send, including information you choose to include about a problem."
          },
          {
            "type": "paragraph",
            "text": "We do not sell personal information. We do not use Apple’s App Tracking Transparency framework, because we do not track you across other companies’ apps and websites for advertising. We do not show third-party advertising in the app."
          }
        ]
      },
      {
        "title": "3. How we use information",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We use information to:"
          },
          {
            "type": "bullets",
            "items": [
              "Create and secure your account, and let you sign in;",
              "Generate images and videos from prompts and files you submit, and show them in your library;",
              "Operate Watch, playback of free, preview, and purchased versions, comments, likes, and shares;",
              "Sell and deliver credits and Studio access, settle usage, and show balance and history;",
              "Moderate content, investigate reports, and enforce our Terms of Use;",
              "Answer support requests;",
              "Measure performance, fix defects, and prevent fraud, abuse, and security incidents;",
              "Comply with law and respond to lawful requests."
            ]
          },
          {
            "type": "paragraph",
            "text": "We do not use your content to sell advertising profiles. We may use prompts, uploads, and outputs to operate safety filters and to investigate abuse. We do not sell those materials."
          }
        ]
      },
      {
        "title": "4. Legal bases for people in the EEA, the UK, and Switzerland",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Where the GDPR, UK GDPR, or Swiss data-protection law applies, we rely on:"
          },
          {
            "type": "bullets",
            "items": [
              "**Contract.** Providing the account, generation, playback, credits, and support you request.",
              "**Legitimate interests.** Securing the Service, preventing fraud, moderating harmful content, understanding aggregate reliability, and improving features, balanced against your rights. You may object as described below.",
              "**Consent.** Where iOS asks you for access to the microphone, speech recognition, photos, contacts, calendars, reminders, or location, and where we ask for consent for an optional use. You can withdraw a device permission in iOS Settings.",
              "**Legal obligation.** Keeping records we must keep, and responding to lawful requests."
            ]
          }
        ]
      },
      {
        "title": "5. AI processing",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Cloud image and video generation sends your prompt, the settings for that request, and any photo you choose to include to our servers and to infrastructure and model providers that process the request for us. Those providers may handle the material only so they can perform the generation, store it for the period we agree for delivery and safety, and must not use it for their own advertising."
          },
          {
            "type": "paragraph",
            "text": "Outputs are produced automatically. They can be wrong or resemble other content. Review them before you publish or rely on them. Do not submit secrets, or personal information you do not want processed for generation, in a prompt or reference image."
          },
          {
            "type": "paragraph",
            "text": "On-device Studio tools process the request on your iPhone. A prompt you later send to cloud generation is handled as cloud content, even if you first composed it on the device."
          }
        ]
      },
      {
        "title": "6. When we share information",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We share personal information with:"
          },
          {
            "type": "bullets",
            "items": [
              "Cloud hosting, storage, and AI processing providers, under contract, and only to run the Service;",
              "Apple, when you make an in-app purchase, restore a purchase, or use an Apple framework such as speech recognition or the photo library. Apple’s privacy policy describes Apple’s own processing;",
              "Other users, when you publish a video, comment, like, or share, to the extent your display name, profile photo, and content are shown;",
              "Professional advisers, and authorities or other parties, when we believe disclosure is required by law or necessary to protect users, the public, or our rights;",
              "A buyer or successor, if we reorganize or sell the Service, in which case we will continue to protect the information as described here or notify you of a material change."
            ]
          },
          {
            "type": "paragraph",
            "text": "We do not share personal information with third parties for their own advertising, and we do not sell or “share” personal information as those words are used in the California Consumer Privacy Act."
          }
        ]
      },
      {
        "title": "7. International transfers",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We are based in Shenzhen, China. We and our service providers may process information in China and in other countries where we or they operate. Those countries may not provide the same level of protection as your home country."
          },
          {
            "type": "paragraph",
            "text": "Where the GDPR or UK GDPR requires a transfer tool, we use an approved mechanism, such as the European Commission’s standard contractual clauses and the UK addendum or International Data Transfer Agreement, together with safeguards appropriate to the transfer. You may ask for a summary of the relevant safeguard by emailing [support@printfilm.com](mailto:support@printfilm.com)."
          }
        ]
      },
      {
        "title": "8. How long we keep information",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We keep account information, content, and purchase records while your account is open and you use the Service. After you close your account, we delete or irreversibly anonymize personal information within a reasonable period, normally within 30 days, except where we need to retain specific records for longer:"
          },
          {
            "type": "bullets",
            "items": [
              "Purchase, refund, and credit records, for tax, accounting, and fraud prevention, typically for up to 7 years or the period required by law;",
              "Safety reports, moderation records, and security logs, for as long as needed to investigate abuse and protect other users;",
              "Information in backups, until the backup cycle overwrites them, after which they are deleted in the ordinary course;",
              "Content you made public, which may persist in another user’s copy, a share preview, or a backup until it is removed in the ordinary course."
            ]
          },
          {
            "type": "paragraph",
            "text": "Guest share identifiers are kept only as long as needed to count and deduplicate share events."
          }
        ]
      },
      {
        "title": "9. Security",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We use encryption in transit (HTTPS) and access controls designed to limit who can see personal information. No method of storage or transmission is completely secure. Use a unique password and keep your device locked."
          }
        ]
      },
      {
        "title": "10. Your choices and rights",
        "blocks": [
          {
            "type": "paragraph",
            "text": "**In the app.** You can review and edit your display name, phone number, and profile photo in your account. You can close your account at Me → Settings → Close Account. Closing an email account requires your password and the confirmation word shown on that screen. Closure signs you out and is a request to delete the account and the personal information described above."
          },
          {
            "type": "paragraph",
            "text": "**Device permissions.** You can turn off microphone, speech recognition, photos, contacts, calendars, reminders, and location access in iOS Settings. If you turn a permission off, the feature that needs it will not work."
          },
          {
            "type": "paragraph",
            "text": "**Access, correction, deletion, and export.** Depending on where you live, you may have the right to ask for a copy of your personal information, to correct it, to delete it, to restrict or object to certain processing, and to receive information you provided in a portable format. You may withdraw consent where processing is based on consent, without affecting processing that took place before withdrawal."
          },
          {
            "type": "paragraph",
            "text": "**EEA, UK, and Switzerland.** You may lodge a complaint with your local supervisory authority. We ask you to contact us first so we can try to resolve the issue."
          },
          {
            "type": "paragraph",
            "text": "**California and other U.S. states.** Residents may have the right to know, delete, and correct personal information, and to appeal a denial. We do not sell personal information and we do not share it for cross-context behavioral advertising. We do not discriminate against you for exercising these rights. We will not ask you to verify your identity in a way that is more burdensome than the request requires. You may use an authorized agent where the law allows; we may still ask you to confirm the request."
          },
          {
            "type": "paragraph",
            "text": "To use any of these rights, email [support@printfilm.com](mailto:support@printfilm.com) from the address on your account, or use Close Account in the app for deletion. We may need to confirm that the request comes from you. We will respond within the time required by applicable law, generally within 30 days, and we will tell you if we need more time."
          }
        ]
      },
      {
        "title": "11. Children",
        "blocks": [
          {
            "type": "paragraph",
            "text": "PrintFilm is not directed to children under 13, and we do not knowingly collect personal information from children under 13. If you believe a child under 13 has given us personal information, email [support@printfilm.com](mailto:support@printfilm.com) and we will delete it. People under 18 should use the Service only with a parent or guardian’s consent."
          }
        ]
      },
      {
        "title": "12. Changes to this policy",
        "blocks": [
          {
            "type": "paragraph",
            "text": "We will post updates at [https://www.printfilm.com/privacy](/privacy) and change the “Last updated” date. If a change materially affects how we use personal information, we will provide a clearer notice, such as in the app or by email, where that is reasonable. The version on the website is the current policy."
          }
        ]
      },
      {
        "title": "13. Contact",
        "blocks": [
          {
            "type": "paragraph",
            "text": "Shenzhen Depei Open Source Data Technology Co., Ltd.\nEmail: [support@printfilm.com](mailto:support@printfilm.com)\nWebsite: [https://www.printfilm.com](https://www.printfilm.com)\nPrivacy Policy: [https://www.printfilm.com/privacy](/privacy)\nTerms of Use: [https://www.printfilm.com/terms](/terms)"
          }
        ]
      }
    ]
  }
}

/** 返回指定法务文档，路由只接受 terms 或 privacy。 */
export function getLegalDoc(slug: 'terms' | 'privacy'): LegalDocument {
  return LEGAL_DOCS[slug]
}
