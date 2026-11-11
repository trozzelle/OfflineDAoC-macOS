import SwiftUI

struct AskSheet: View {
    @EnvironmentObject var model: AppModel
    let request: AskRequest

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(request.question).fixedSize(horizontal: false, vertical: true)
            HStack {
                Spacer()
                // Escape always means No; Return picks daoc's own default. A button holds one
                // shortcut, so when the default is No, Return goes to an invisible twin of No.
                Button("No") { model.answer(request, false) }
                    .keyboardShortcut(.cancelAction)
                    .background {
                        if !request.defaultAnswer {
                            Button("") { model.answer(request, false) }
                                .keyboardShortcut(.defaultAction)
                                .opacity(0)
                                .accessibilityHidden(true)
                        }
                    }
                Button("Yes") { model.answer(request, true) }
                    .keyboardShortcut(request.defaultAnswer ? .defaultAction : nil)
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
