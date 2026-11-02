import SwiftUI

struct AskSheet: View {
    @EnvironmentObject var model: AppModel
    let request: AskRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(request.question).fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                // Return picks daoc's own default; Escape picks the other answer.
                Button("No") { model.answer(request, false) }
                    .keyboardShortcut(request.defaultAnswer ? .cancelAction : .defaultAction)
                Button("Yes") { model.answer(request, true) }
                    .keyboardShortcut(request.defaultAnswer ? .defaultAction : .cancelAction)
            }
        }
        .padding(24)
        .frame(width: 420)
    }
}

struct SecretSheet: View {
    @EnvironmentObject var model: AppModel
    let request: SecretRequest
    @State private var account = ""
    @State private var password = ""

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Game account").font(.headline)
            TextField("Account name", text: $account)
            SecureField("Password", text: $password)
            HStack {
                Spacer()
                Button("Cancel") { model.cancel(request) }.keyboardShortcut(.cancelAction)
                Button("Save") { model.answer(request, account: account, password: password) }
                    .keyboardShortcut(.defaultAction)
                    .disabled(account.isEmpty || password.isEmpty)
            }
        }
        .padding(24)
        .frame(width: 360)
    }
}
