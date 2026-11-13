frappe.ui.form.on("Push Campaign Run", {
	refresh(frm) {
		frm.disable_save();
		frm.add_custom_button(__("Delivery History"), () =>
			frappe.set_route("List", "Push Campaign Delivery", { run: frm.doc.name }));
	},
});
