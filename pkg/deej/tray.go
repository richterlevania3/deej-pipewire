package deej

// Tray support removed for this build — deej runs headless (no GTK/appindicator
// build deps). Stop with Ctrl+C or SIGTERM.

func (d *Deej) initializeTray(onDone func()) {
	d.logger.Info("Tray disabled in this build, running headless")
	onDone()
}

func (d *Deej) stopTray() {}
