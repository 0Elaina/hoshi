package com.nep.auth.listener;

import org.springframework.context.event.EventListener;
import org.springframework.stereotype.Component;
import org.springframework.transaction.annotation.Propagation;
import org.springframework.transaction.annotation.Transactional;

import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.nep.auth.mapper.AuthSessionMapper;
import com.nep.auth.model.entity.AuthSession;
import com.nep.user.event.UserSecurityChangedEvent;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Component
@RequiredArgsConstructor
public class UserSecurityChangedListener {
    private final AuthSessionMapper authSessionMapper;

    /**
     * 用户安全信息变更监听
     * 必须在事务中执行
     * 
     * @param event 用户安全信息变更事件
     */
    @EventListener
    @Transactional(propagation = Propagation.MANDATORY, rollbackFor = Exception.class)
    public void onUserSecurityChanged(UserSecurityChangedEvent event) {
        int count = authSessionMapper.update(null, new LambdaUpdateWrapper<AuthSession>()
                .eq(AuthSession::getUserId, event.userId())
                .set(AuthSession::getRevokedAt, event.occurredAt())
                .set(AuthSession::getUpdatedAt, event.occurredAt())
                .isNull(AuthSession::getRevokedAt));
        log.info("同步撤销用户会话完成, userId={}, revokedCount={}", event.userId(), count);
    }
}
