package com.nep.user.service.impl;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import com.nep.common.exception.BusinessException;
import com.nep.user.constant.UserApiCode;
import com.nep.user.entity.User;
import com.nep.user.enums.UserRole;
import com.nep.user.enums.UserStatus;
import com.nep.user.mapper.UserMapper;
import com.nep.user.service.UserService;
import com.nep.user.vo.UserVO;

import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;

@Slf4j
@Service
@RequiredArgsConstructor
public class UserServiceImpl implements UserService {
    private final UserMapper userMapper;
    private final PasswordEncoder passwordEncoder;

    /**
     * 创建用户
     * 
     * @param username 用户名
     * @param password 密码
     * @param nickname 昵称
     * @return 创建后的用户
     */
    @Override
    @Transactional(rollbackFor = Exception.class)
    public UserVO createUser(String username, String password, String nickname) {
        nickname = normalizeNickname(nickname, username);
        String passwordHash = passwordEncoder.encode(password);
        User user = new User();
        user.setUsername(username);
        user.setPasswordHash(passwordHash);
        user.setNickname(nickname);
        user.setRole(UserRole.USER.name());
        user.setStatus(UserStatus.ENABLED.name());

        try {
            userMapper.insert(user);
        } catch (DuplicateKeyException e) {
            throw new BusinessException(UserApiCode.USERNAME_TAKEN);
        }
        log.info("创建新的用户成功, id={}", user.getId());
        return UserVO.of(user);
    }

    private String normalizeNickname(String nickname, String username) {
        if (!StringUtils.hasText(nickname))
            return username;
        return nickname.strip();
    }
}
