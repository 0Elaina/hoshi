package com.nep.user.model.vo;

import java.time.OffsetDateTime;

import com.nep.user.model.entity.User;

import lombok.Builder;

@Builder
public record UserVO(
        String id,
        String username,
        String nickname,
        String role,
        String status,
        OffsetDateTime createdAt,
        OffsetDateTime updatedAt) {

    public static UserVO of(User user) {
        return UserVO.builder()
                .id(user.getId().toString())
                .username(user.getUsername())
                .nickname(user.getNickname())
                .role(user.getRole())
                .status(user.getStatus())
                .createdAt(user.getCreatedAt())
                .updatedAt(user.getUpdatedAt())
                .build();
    }
}
