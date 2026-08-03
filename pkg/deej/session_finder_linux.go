package deej

import (
	"fmt"
	"net"

	"github.com/jfreymuth/pulse/proto"
	"go.uber.org/zap"
)

type paSessionFinder struct {
	logger        *zap.SugaredLogger
	sessionLogger *zap.SugaredLogger

	client *proto.Client
	conn   net.Conn
}

func newSessionFinder(logger *zap.SugaredLogger) (SessionFinder, error) {
	client, conn, err := proto.Connect("")
	if err != nil {
		logger.Warnw("Failed to establish PulseAudio connection", "error", err)
		return nil, fmt.Errorf("establish PulseAudio connection: %w", err)
	}

	request := proto.SetClientName{
		Props: proto.PropList{
			"application.name": proto.PropListString("deej"),
		},
	}
	reply := proto.SetClientNameReply{}

	if err := client.Request(&request, &reply); err != nil {
		return nil, err
	}

	sf := &paSessionFinder{
		logger:        logger.Named("session_finder"),
		sessionLogger: logger.Named("sessions"),
		client:        client,
		conn:          conn,
	}

	sf.logger.Debug("Created PA session finder instance")

	return sf, nil
}

func (sf *paSessionFinder) GetAllSessions() ([]Session, error) {
	sessions := []Session{}

	// get the master sink session
	masterSink, err := sf.getMasterSinkSession()
	if err == nil {
		sessions = append(sessions, masterSink)
	} else {
		sf.logger.Warnw("Failed to get master audio sink session", "error", err)
	}

	// get the master source session
	masterSource, err := sf.getMasterSourceSession()
	if err == nil {
		sessions = append(sessions, masterSource)
	} else {
		sf.logger.Warnw("Failed to get master audio source session", "error", err)
	}

	// enumerate sink inputs and add sessions along the way
	if err := sf.enumerateAndAddSessions(&sessions); err != nil {
		sf.logger.Warnw("Failed to enumerate audio sessions", "error", err)
		return nil, fmt.Errorf("enumerate audio sessions: %w", err)
	}

	return sessions, nil
}

// PulseAudio subscription bit for sink inputs, and the facility field encoded
// in a SubscribeEvent (see pulse/def.h PA_SUBSCRIPTION_*). Not exported by the
// jfreymuth/pulse proto package, so defined here.
const (
	paSubscriptionMaskSinkInput  = 0x0004
	paSubscriptionEventFacility  = 0x000F
	paSubscriptionEventSinkInput = 0x0002
	paSubscriptionEventType      = 0x0030
	paSubscriptionEventNew       = 0x0000
)

// SubscribeToSinkInputEvents asks pipewire-pulse to notify us whenever a sink
// input (application stream) appears, changes, or goes away, and returns a
// channel that ticks once per such event. deej uses this to re-apply the mapped
// slider volume the instant an app spawns a new stream (e.g. Firefox on tab
// focus / audio restart), rather than waiting for the next poll.
func (sf *paSessionFinder) SubscribeToSinkInputEvents() (chan struct{}, error) {
	events := make(chan struct{}, 1)

	// the proto client calls Callback on its read loop for every unsolicited
	// message; we only act on sink-input SubscribeEvents. Non-blocking send so
	// we never stall that loop (the caller coalesces bursts anyway).
	sf.client.Callback = func(msg interface{}) {
		if evt, ok := msg.(*proto.SubscribeEvent); ok {
			// only react to NEW sink inputs. change/remove events include the
			// ones our own SetVolume triggers, which would otherwise feed back
			// into an endless re-assert loop.
			if evt.Event&paSubscriptionEventFacility == paSubscriptionEventSinkInput &&
				evt.Event&paSubscriptionEventType == paSubscriptionEventNew {
				select {
				case events <- struct{}{}:
				default:
				}
			}
		}
	}

	if err := sf.client.Request(&proto.Subscribe{Mask: paSubscriptionMaskSinkInput}, nil); err != nil {
		sf.logger.Warnw("Failed to subscribe to sink input events", "error", err)
		return nil, fmt.Errorf("subscribe to sink input events: %w", err)
	}

	sf.logger.Debug("Subscribed to PulseAudio sink-input events")

	return events, nil
}

func (sf *paSessionFinder) Release() error {
	if err := sf.conn.Close(); err != nil {
		sf.logger.Warnw("Failed to close PulseAudio connection", "error", err)
		return fmt.Errorf("close PulseAudio connection: %w", err)
	}

	sf.logger.Debug("Released PA session finder instance")

	return nil
}

func (sf *paSessionFinder) getMasterSinkSession() (Session, error) {
	request := proto.GetSinkInfo{
		SinkIndex: proto.Undefined,
	}
	reply := proto.GetSinkInfoReply{}

	if err := sf.client.Request(&request, &reply); err != nil {
		sf.logger.Warnw("Failed to get master sink info", "error", err)
		return nil, fmt.Errorf("get master sink info: %w", err)
	}

	// create the master sink session
	sink := newMasterSession(sf.sessionLogger, sf.client, reply.SinkIndex, reply.Channels, true)

	return sink, nil
}

func (sf *paSessionFinder) getMasterSourceSession() (Session, error) {
	request := proto.GetSourceInfo{
		SourceIndex: proto.Undefined,
	}
	reply := proto.GetSourceInfoReply{}

	if err := sf.client.Request(&request, &reply); err != nil {
		sf.logger.Warnw("Failed to get master source info", "error", err)
		return nil, fmt.Errorf("get master source info: %w", err)
	}

	// create the master source session
	source := newMasterSession(sf.sessionLogger, sf.client, reply.SourceIndex, reply.Channels, false)

	return source, nil
}

func (sf *paSessionFinder) enumerateAndAddSessions(sessions *[]Session) error {
	request := proto.GetSinkInputInfoList{}
	reply := proto.GetSinkInputInfoListReply{}

	if err := sf.client.Request(&request, &reply); err != nil {
		sf.logger.Warnw("Failed to get sink input list", "error", err)
		return fmt.Errorf("get sink input list: %w", err)
	}

	for _, info := range reply {
		// deej keys sessions on the process binary, but some clients register a
		// stream without application.process.binary (e.g. High Tide on certain
		// audio backends). Fall back to other stable identifiers so those streams
		// are still controllable.
		name, ok := info.Properties["application.process.binary"]
		if !ok {
			for _, key := range []string{"node.name", "application.name", "media.name"} {
				if v, has := info.Properties[key]; has {
					name, ok = v, true
					break
				}
			}
		}

		if !ok {
			sf.logger.Warnw("Sink input has no usable identifier, skipping",
				"sinkInputIndex", info.SinkInputIndex)

			continue
		}

		// create the deej session object
		newSession := newPASession(sf.sessionLogger, sf.client, info.SinkInputIndex, info.Channels, name.String())

		// add it to our slice
		*sessions = append(*sessions, newSession)

	}

	return nil
}
