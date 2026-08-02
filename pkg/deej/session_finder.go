package deej

// SessionFinder represents an entity that can find all current audio sessions
type SessionFinder interface {
	GetAllSessions() ([]Session, error)

	// SubscribeToSinkInputEvents returns a channel that signals whenever an
	// audio stream is added/changed/removed, so volumes can be re-applied
	// immediately instead of only on the next poll.
	SubscribeToSinkInputEvents() (chan struct{}, error)

	Release() error
}
