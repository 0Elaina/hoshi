package com.nep.user.event;

import java.time.OffsetDateTime;

public record UserSecurityChangedEvent(
        Long userId,
        OffsetDateTime occurredAt) {

}
