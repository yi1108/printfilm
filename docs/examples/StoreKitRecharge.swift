import Foundation
import StoreKit

// iOS 15+ integration example. Supply your authenticated HTTPS/Keychain adapter.
// The adapter must durably reuse an intent key for a retried create-order request.
struct RechargeOffer {
    let skuID: String
    let productID: String
    let expectedPrices: [String: Int]
    let creditFen: Int
}
struct RechargeIntent {
    let id: Int
    let productID: String
    let accountToken: UUID
    let expectedPrices: [String: Int]
}
struct RechargeConfirmation {
    let finishTransaction: Bool
    let credited: Bool
}
protocol RechargeAPI {
    func createIntent(skuID: String, idempotencyKey: String) async throws -> RechargeIntent
    func verify(jws: String, intentID: Int?) async throws -> RechargeConfirmation
    func refreshWallet() async throws
}

actor StoreKitRecharge {
    enum RechargeError: Error { case productUnavailable, priceMismatch, unverified, notConfirmed }
    enum PurchaseState { case credited, refunded, pending, cancelled }
    private let api: any RechargeAPI
    private var inFlight: Set<UInt64> = []
    init(api: any RechargeAPI) { self.api = api }

    private func matches(_ product: Product, prices: [String: Int]) -> Bool {
        guard product.type == .consumable,
              let expected = prices[product.priceFormatStyle.currencyCode] else { return false }
        return product.price * Decimal(100) == Decimal(expected)
    }

    func buy(_ offer: RechargeOffer, persistedIntentKey: String) async throws -> PurchaseState {
        guard let product = try await Product.products(for: [offer.productID]).first else {
            throw RechargeError.productUnavailable
        }
        guard matches(product, prices: offer.expectedPrices) else { throw RechargeError.priceMismatch }
        let intent = try await api.createIntent(skuID: offer.skuID, idempotencyKey: persistedIntentKey)
        guard intent.productID == product.id, matches(product, prices: intent.expectedPrices) else {
            throw RechargeError.priceMismatch
        }
        switch try await product.purchase(options: [.appAccountToken(intent.accountToken)]) {
        case .success(let result):
            let credited = try await fulfill(result, intentID: intent.id)
            return credited ? .credited : .refunded
        case .pending: return .pending
        case .userCancelled: return .cancelled
        @unknown default: throw RechargeError.notConfirmed
        }
    }

    // Run as a retained Task after sign-in; cancel on sign-out. Do not log JWS.
    func listen(onError: @Sendable (Error) -> Void) async {
        for await result in Transaction.updates {
            if Task.isCancelled { return }
            do { _ = try await fulfill(result, intentID: nil) }
            catch { onError(error) } // Leave unfinished; retry on foreground/network recovery.
        }
    }

    func retryUnfinished(onError: @Sendable (Error) -> Void) async {
        for await result in Transaction.unfinished {
            if Task.isCancelled { return }
            do { _ = try await fulfill(result, intentID: nil) }
            catch { onError(error) }
        }
    }

    private func fulfill(_ result: VerificationResult<Transaction>, intentID: Int?) async throws -> Bool {
        guard case .verified(let transaction) = result else { throw RechargeError.unverified }
        guard !inFlight.contains(transaction.id) else { throw RechargeError.notConfirmed }
        inFlight.insert(transaction.id)
        defer { inFlight.remove(transaction.id) }
        let response = try await api.verify(jws: result.jwsRepresentation, intentID: intentID)
        guard response.finishTransaction else { throw RechargeError.notConfirmed }
        await transaction.finish()
        // A refresh failure must not trigger a second purchase. Server already fulfilled it.
        try? await api.refreshWallet()
        return response.credited
    }
}
