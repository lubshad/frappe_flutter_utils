frappe.ui.form.on("Flutter Utils Settings", {
	send_test_message(frm) {
		const channel = frm.doc.enable_mobile_otp ? "mobile" : "email";
		const fieldLabel = channel === "mobile" ? "recipient mobile number" : "recipient email";

		frappe.prompt(
			[
				{
					fieldname: "recipient",
					fieldtype: "Data",
					label: fieldLabel,
					reqd: 1,
				},
			],
			(values) => {
				frm.call("send_test_message", {
					channel,
					recipient: values.recipient,
				}).then((r) => {
					if (r.message?.message) {
						frappe.msgprint(r.message.message);
					}
				});
			},
			"Send Test Message",
			"Send"
		);
	},
});
